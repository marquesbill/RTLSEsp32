"""Rastreador RTLS: filtro de particulas sobre RSSI cru, com restricao de planta baixa.
Substitui o pipeline multilateracao->Kalman (3.4x melhor na mediana, ver compare_filters.py).

A verossimilhanca e avaliada em dB, onde o ruido de fato e gaussiano. Converter dB->metros
antes do ajuste injeta +13% de vies log-normal.

Rodar: python3 tracker.py   (auto-teste no final)
"""
import numpy as np

def _dentro(P, poly):
    """Ponto-em-poligono por lancamento de raio, vetorizado sobre as particulas."""
    x, y = P[:, 0], P[:, 1]
    dentro = np.zeros(len(P), bool)
    j = len(poly) - 1
    for i in range(len(poly)):
        (xi, yi), (xj, yj) = poly[i], poly[j]
        dentro ^= ((yi > y) != (yj > y)) & \
                  (x < (xj - xi)*(y - yi)/((yj - yi) or 1e-300) + xi)
        j = i
    return dentro


def _ccw(a, b, c):
    return (c[..., 1]-a[..., 1])*(b[..., 0]-a[..., 0]) > (b[..., 1]-a[..., 1])*(c[..., 0]-a[..., 0])

class Floorplan:
    """Paredes como segmentos (M,2,2). Usada so no modelo de movimento: particula
    nao atravessa parede. O modelo de medida ignora paredes de proposito — a perda
    por parede vira outlier, absorvido pela cauda pesada da verossimilhanca."""

    def __init__(self, walls, bounds, rooms=None):
        self.walls = np.asarray(walls, float).reshape(-1, 2, 2)
        self.xmin, self.ymin, self.xmax, self.ymax = map(float, bounds)
        # {nome: [(x,y), ...]}. Sem isto nao ha saida por comodo — e a saida por
        # comodo e a PRIMARIA: metro so depois que V9 autorizar.
        self.rooms = {k: [tuple(map(float, q)) for q in v]
                      for k, v in (rooms or {}).items()}

    def cruza(self, p, q):
        """Quantas paredes o segmento de cada particula ate o ponto fixo q cruza.
        p (N,2), q (2,) -> (N,) inteiro. Mesma geometria do blocked, mas contando."""
        q = np.broadcast_to(np.asarray(q, float), p.shape)
        k = np.zeros(len(p), np.int16)
        for w in self.walls:
            k += ((_ccw(p, w[0], w[1]) != _ccw(q, w[0], w[1])) &
                  (_ccw(p, q, w[0]) != _ccw(p, q, w[1]))).astype(np.int16)
        return k

    def blocked(self, p, q):
        out = np.zeros(len(p), bool)
        for w in self.walls:
            out |= (_ccw(p, w[0], w[1]) != _ccw(q, w[0], w[1])) & \
                   (_ccw(p, q, w[0]) != _ccw(p, q, w[1]))
        return out

    def sample(self, n, rng):
        # ponytail: amostra a bounding box, nao o poligono caminhavel.
        # trocar por amostragem do poligono se a planta tiver muita area morta.
        return np.column_stack([rng.uniform(self.xmin, self.xmax, n),
                                rng.uniform(self.ymin, self.ymax, n)])

    def clip(self, p):
        np.clip(p[:, 0], self.xmin, self.xmax, out=p[:, 0])
        np.clip(p[:, 1], self.ymin, self.ymax, out=p[:, 1])
        return p


class _Track:
    __slots__ = ("p", "v", "w", "t", "n_upd", "b", "b_fixo", "m", "ess")
    def __init__(self, p, v, t):
        self.p, self.v, self.t, self.n_upd = p, v, t, 0
        # m: modo por particula, 0=parado 1=andando. Sem isto a velocidade e um
        # passeio aleatorio NAO amortecido: num alvo parado ela vagueia ate a
        # nuvem inteira herdar uma velocidade media nao-nula na reamostragem e
        # andar balisticamente. E o mecanismo dos 50 m/20 min MEDIDOS no CYD.
        self.m = np.zeros(len(p), np.int8)
        self.ess = float(len(p))
        # b: vies de Ptx do alvo, desconhecida. Estado LENTO por media movel do
        # residuo — nao dupla diferenca por pacote, que injeta o ruido de duas
        # leituras onde ha um so parametro por aparelho.
        self.b, self.b_fixo = 0.0, False
        self.w = np.full(len(p), 1.0/len(p))


class Tracker:
    """anchors: dict {anchor_id: (x, y)}. Uma instancia serve todos os dispositivos."""

    def __init__(self, anchors, floorplan, A=-45.0, n_exp=2.8, sigma=3.4,
                 n_particles=600, q=0.6, v_max=2.5, ttl=120.0, ll_floor=-8.0, seed=0,
                 b_alfa=0.0, z_alvo=1.1, W=0.0, piso=None, alpha=1.0, nu=None,
                 t_parado=60.0, t_andando=20.0, jitter_parado=0.03, ganho=None,
                 temporal=None):
        """sigma 3,4 dB e MEDIDO (CYD; V1 remede na C3 a 2 s). O 6,0 anterior era
        chute — a bancada simulada gera com 6,0 e por isso passa 6,0 explicito.

        b_alfa=0 (DESLIGADO) e uma correcao da proposta que a medicao reprovou.
        MEDIDO na bancada, 10 trilhas: sem vies 3,065 -> 3,111 m (custa 0,05 m);
        com alvo 8 dB acima 3,60 -> 3,59 m (nao ganha nada). Um offset de Ptx e
        COMUM a todas as ancoras e se cancela na comparacao entre elas, que e o
        que localiza. Fica implementado para ligar quando V9 mostrar um caso que
        justifique; o caminho que serve de verdade e fixa_vies() na tag de Ptx
        conhecida, que nao estima nada.

        ABERTO: este default e 0, mas vivo.novo_tracker passa 0,05 e loo.online
        passa 0,2 — tres valores, nenhuma medicao que reconcilie os tres. So a
        campanha rotulada resolve; ate la nao mexer, porque b_alfa muda o erro
        de qualquer A/n/W e contamina qualquer A/B de modelo."""
        self.ids = list(anchors)
        # Ancora aceita (x, y) ou (x, y, z). Com z, a distancia do modelo vira 3D
        # contra z_alvo. Aqui isso NAO e detalhe: as tomadas estao em duas alturas
        # (0,30 no rodape, 1,10 na cozinha/WC) e as distancias sao de 1-3 m, entao
        # o dz de 0,80 m e um VIES sistematico de ate ~1,5 dB — da ordem do sigma.
        _A = np.array([anchors[i] for i in self.ids], float)
        self.P, self.z = _A[:, :2], (_A[:, 2] if _A.shape[1] > 2 else None)
        self.idx = {a: k for k, a in enumerate(self.ids)}
        self.fp, self.A, self.n_exp, self.sigma = floorplan, A, n_exp, sigma
        # `ll_floor and ttl`: os dois nasceram do mesmo modo robusto antigo, entao
        # ll_floor falsy DESLIGA o ttl junto. Com o default (-8.0) e com todo
        # chamador de hoje o ttl vale; passar ll_floor=0 poria ttl=0 e expire()
        # mataria TODA trilha a cada chamada, calado. Trocar um exige trocar o outro.
        self.n, self.q, self.v_max, self.ttl = n_particles, q, v_max, ll_floor and ttl
        self.ll_floor, self.b_alfa, self.z_alvo = ll_floor, b_alfa, z_alvo
        # W=0 mantem o comportamento antigo (parede como outlier). Com W>0 o modelo
        # de medida passa a contar paredes, o que casa com o ajuste: ajuste.py SEMPRE
        # estimou A junto com um termo de parede, entao usar esse A sem o termo deixa
        # o modelo otimista nos enlaces com parede e empurra a nuvem para fora.
        self.W = float(W)
        # piso: RSSI abaixo do qual a leitura esta CENSURADA — o radio so reporta os
        # picos e a mediana MENTE para cima (campanha.py ja mediu isso e filtra em
        # -93, com piso real -101). Passar um valor censurado como medida diz ao
        # filtro "estou a 24 m desta ancora", o que empurra a nuvem para o lado
        # oposto. MEDIDO no CYD com gabarito: 1,70 -> 0,80 m so por tratar o piso.
        self.piso = piso
        # ganho(P, ai, z_alvo) -> (N, len(ai)) dB somados ao mu: offset por ancora
        # + padrao direcional vindos de modelo/padrao.py. None e o estado NORMAL:
        # so entra se a transferencia leave-one-point-out aprovar (hoje NAO aprova,
        # ver modelo/padrao.json). Aqui e so o gancho — a decisao mora la.
        self.ganho = ganho
        # temporal: modelo diurno de modelo/temporal.py, ou None (estado NORMAL).
        # Entrega DUAS coisas por hora: mu(t), um deslocamento comum a todas as
        # ancoras, e escala(t), um multiplicador de sigma. So o segundo e sempre
        # seguro — alargar sigma numa hora barulhenta so faz o filtro confiar
        # menos, nunca o move para lugar nenhum.
        #
        # ARMADILHA: mu(t) entra na MESMA fenda que tr.b. Com b_alfa>0 os dois
        # estimariam o mesmo deslocamento e brigariam — e b_alfa e exatamente o
        # reajuste cego que 06-transferencia reprovou. Por isso b_alfa nasce 0.
        # Se voce ligar os dois, o vies vira soma de duas estimativas do mesmo
        # numero. Fora das horas com dado de treino, temporal devolve 0 e 1: o
        # rastreador roda como hoje, sem extrapolar Fourier as cegas.
        self.temporal = temporal
        # alpha<1 (tempering): o residuo estrutural desta casa e CONSTANTE no tempo
        # (+8,7 dB no enlace 5<->3, +16 dB do CYD para a 5, estavel a 1 dB em 90 min).
        # Multiplica-lo 120x/min como se fossem evidencias novas e independentes deixa
        # a posterior arbitrariamente confiante num lugar errado — ate uma flutuacao
        # virar o quadro. Esse e o salto de 1,28 m com ESS colapsado.
        self.alpha = float(alpha)
        # nu: graus de liberdade da Student-t. Substitui o ll_floor, que e robustez
        # da versao ruim — acima de 4 sigma TODO residuo vale igual, criando um plato
        # onde a particula 12 dB errada empata com a 30 dB errada.
        self.nu = nu
        # tempos medios de permanencia em cada modo, em segundos
        self.t_parado, self.t_andando = float(t_parado), float(t_andando)
        self.jitter_parado = float(jitter_parado)
        self.rng = np.random.default_rng(seed)
        self.tracks = {}

    # ---- inicializacao ----
    def _seed(self, _ai, _rssi, t):     # _: a medida NAO entra no prior, de proposito
        """Prior uniforme. A atualizacao de medida vem logo em seguida e ja concentra
        a nuvem — nao ha por que semear de uma multilateracao.

        Medido: semear de multilateracao PIORA (regime 3.00 -> 5.12 m, p99 11.6 -> 38.0 m),
        porque o palpite carrega o vies log-normal de +13% da conversao dB->metros e o
        espalhamento estreito trava a nuvem nessa moda errada.

        ponytail: uniforme na bounding box basta ate ~2000 m2 com 600 particulas.
        Em area de aeroporto (>20000 m2) a densidade cai demais: subir n_particles no
        primeiro passo e podar apos a primeira medida, ou semear na regiao das ancoras
        que ouviram (regiao, nao ponto — ponto reintroduz o vies).
        """
        return _Track(self.fp.sample(self.n, self.rng),
                      self.rng.normal(0, 0.5, (self.n, 2)), t)

    # ---- modelo de medida (trocavel) ----
    def loglik(self, P, ai, rssi, b=0.0, esc=1.0):
        """Path loss log-distancia. Subclasse troca isto por um mapa de radio
        sem tocar em movimento, planta, reamostragem ou ciclo de vida (fingerprint.py)."""
        d = self._dist(np.linalg.norm(P[:, None, :] - self.P[None, ai, :], axis=2), ai)
        mu = self.A - 10*self.n_exp*np.log10(d)
        if self.W:
            mu = mu - self.W*np.column_stack([self.fp.cruza(P, self.P[k]) for k in ai])
        if self.ganho is not None:
            mu = mu + self.ganho(P, ai, self.z_alvo)
        sig = self.sigma*esc          # esc vem do modelo diurno; 1.0 = como hoje
        z = ((rssi - b) - mu)/sig
        ll = (-0.5*(self.nu + 1.0)*np.log1p(z*z/self.nu) if self.nu else -0.5*z*z)
        if self.piso is not None:
            # censurado nao e "sem informacao": ainda diz "nao estou perto desta
            # ancora". Penaliza so quando o modelo previa que ela OUVIRIA alto —
            # dobradica de um lado so, que e a verossimilhanca da cauda sem scipy.
            cens = (rssi - b) <= self.piso
            ll = np.where(cens, -0.5*(np.maximum(mu - self.piso, 0)/sig)**2, ll)
        return ll if self.nu else np.maximum(ll, self.ll_floor)

    def _dist(self, dxy, ai):
        """2D quando a ancora nao tem z; senao Pitagoras com o desnivel ancora-alvo."""
        if self.z is None:
            return np.maximum(dxy, 0.5)
        return np.maximum(np.hypot(dxy, self.z[ai] - self.z_alvo), 0.5)

    def fixa_vies(self, dev, b):
        """Tag de Ptx conhecida (o equipamento): trava b em vez de estimar."""
        tr = self.tracks.get(dev)
        if tr is not None:
            tr.b, tr.b_fixo = float(b), True

    # ---- passo ----
    def update(self, dev, obs, t):
        """obs: {anchor_id: rssi_dBm}. Devolve (x, y) estimado ou None."""
        pairs = [(self.idx[a], r) for a, r in obs.items()
                 if a in self.idx and r is not None and np.isfinite(r)]
        ai = np.array([k for k, _ in pairs], int)
        rssi = np.array([r for _, r in pairs], float)

        tr = self.tracks.get(dev)
        if tr is None or t - tr.t > self.ttl:
            if not len(ai):
                return None
            tr = self.tracks[dev] = self._seed(ai, rssi, t)
        else:
            dt = max(t - tr.t, 1e-3)
            tr.t = t
            # cadeia de Markov de 2 estados por particula: quem esta parado tem
            # velocidade EXATAMENTE zero (nao "pequena"), e so 3 cm/passo de folga.
            u = self.rng.random(self.n)
            fica = np.where(tr.m == 0, np.exp(-dt/self.t_parado), np.exp(-dt/self.t_andando))
            tr.m = np.where(u < fica, tr.m, 1 - tr.m).astype(np.int8)
            mov = tr.m == 1
            tr.v[~mov] = 0.0
            tr.v[mov] += self.rng.normal(0, self.q*dt, (int(mov.sum()), 2))
            sp = np.linalg.norm(tr.v, axis=1, keepdims=True)   # pedestre nao voa
            tr.v *= np.minimum(1.0, self.v_max/np.maximum(sp, 1e-9))
            pn = tr.p + tr.v*dt
            pn[mov] += self.rng.normal(0, self.q*dt**2/2, (int(mov.sum()), 2))
            pn[~mov] += self.rng.normal(0, self.jitter_parado, (int((~mov).sum()), 2))
            bad = self.fp.blocked(tr.p, pn)
            pn[bad] = tr.p[bad]
            tr.v[bad] *= -0.3
            tr.p = self.fp.clip(pn)

        # Correcao 2: a verossimilhanca soma APENAS as ancoras que reportaram neste
        # passo (pairs sai de obs). Ancora ausente e termo ausente — nunca um RSSI
        # de piso, que empurraria a nuvem para longe dela como se tivesse ouvido.
        if len(ai):
            b, esc = tr.b, 1.0
            if self.temporal is not None:
                b = b + float(self.temporal.mu(t)[0])
                esc = float(self.temporal.escala(t)[0])
            lw = np.log(tr.w + 1e-300) + self.alpha*self.loglik(tr.p, ai, rssi, b, esc).sum(1)
            lw -= lw.max()
            w = np.exp(lw); s = w.sum()
            tr.w = np.full(self.n, 1.0/self.n) if not np.isfinite(s) or s <= 0 else w/s
            tr.n_upd += 1

        est = tr.p.T @ tr.w
        # b_k: media movel do residuo no estimador. Precisa de >= 2 ancoras, senao
        # b e posicao sao o mesmo parametro e o vies engole o erro de posicao.
        if len(ai) >= 2 and self.b_alfa and not tr.b_fixo:
            d = self._dist(np.linalg.norm(est - self.P[ai], axis=1), ai)
            mu = self.A - 10*self.n_exp*np.log10(d)
            if self.W:      # sem isto o vies come a perda media de parede e conta duas vezes
                mu = mu - self.W*np.array([self.fp.cruza(est[None], self.P[k])[0] for k in ai])
            res = float(np.mean(rssi - mu))
            tr.b += self.b_alfa*(res - tr.b)
        tr.ess = 1.0/np.sum(tr.w**2)     # termometro: alvo e 30-60% de n
        if tr.ess < self.n/2:                                  # reamostra por ESS
            k = self.rng.choice(self.n, self.n, p=tr.w)
            tr.p, tr.v, tr.m = tr.p[k], tr.v[k], tr.m[k]
            tr.w = np.full(self.n, 1.0/self.n)
        return est

    def p_parado(self, dev):
        """Peso da massa no modo parado. Melhor termometro de saude que existe aqui:
        alvo na mesa tem de dar alto, pessoa andando tem de despencar."""
        tr = self.tracks.get(dev)
        return float(tr.w[tr.m == 0].sum()) if tr is not None else float("nan")

    def spread(self, dev):
        """Desvio-padrao da nuvem, em metros: incerteza publicavel junto da posicao."""
        tr = self.tracks.get(dev)
        if tr is None: return np.inf
        mu = tr.p.T @ tr.w
        return float(np.sqrt(((tr.p-mu)**2).sum(1) @ tr.w))

    def nuvem(self, dev, k=300):
        """k particulas AMOSTRADAS PELO PESO -> [[x,y],...]. Densidade = posterior.

        Desenhar as particulas cruas mentiria: depois de uma medida forte quase
        todo o peso mora numa fracao delas, e um sorteio uniforme pintaria como
        provavel exatamente o que o filtro acabou de descartar."""
        tr = self.tracks.get(dev)
        if tr is None:
            return []
        w = tr.w / tr.w.sum()
        i = self.rng.choice(len(tr.p), min(k, len(tr.p)), p=w)
        return [[round(float(a), 2), round(float(b), 2)] for a, b in tr.p[i]]

    def comodo(self, dev):
        """Posterior por comodo: soma dos pesos das particulas dentro de cada poligono.
        Saida PRIMARIA. Devolve {} sem planta de comodos — nao chuta um comodo a
        partir do ponto medio, que e justamente o numero que ainda nao vale."""
        tr = self.tracks.get(dev)
        if tr is None or not self.fp.rooms:
            return {}
        return {k: float(tr.w[_dentro(tr.p, poly)].sum())
                for k, poly in self.fp.rooms.items()}

    def expire(self, t):
        for d in [d for d, tr in self.tracks.items() if t - tr.t > self.ttl]:
            del self.tracks[d]


def demo():
    """Auto-teste completo do filtro na BANCADA sintetica (nao no sitio): geometria
    fixa de 40x30 m com 8 ancoras, para que o numero de erro seja comparavel entre
    versoes do codigo. O sitio de cada um entra pelos demos de loo/estaticos/vivo."""
    import time
    from ferramentas.compare_filters import WALLS, ANC, observe, path, SIGMA   # cenario da bancada

    # Comodos da bancada: metade oeste e metade leste. Servem so para exercitar a
    # saida primaria; a planta de verdade vem de V0 (trena).
    COMODOS = {"oeste": [(0, 0), (20, 0), (20, 30), (0, 30)],
               "leste": [(20, 0), (40, 0), (40, 30), (20, 30)]}
    fp = Floorplan(WALLS, (0, 0, 40, 30), rooms=COMODOS)
    anchors = {f"anc{i}": tuple(p) for i, p in enumerate(ANC)}
    rng = np.random.default_rng(42)
    truth = path(); dt = 2.0

    all_e, all_e0, sp = [], [], []
    t0 = time.perf_counter()
    for trial in range(10):
        # sigma=SIGMA (6,0) porque e com 6,0 que ESTA bancada gera. O default da
        # classe e 3,4, que e o medido no hardware — sao coisas diferentes.
        tk = Tracker(anchors, fp, seed=trial, sigma=SIGMA)
        obs = np.array([observe(x, rng) for x in truth])
        e = []
        for i, r in enumerate(obs):
            o = {f"anc{j}": v for j, v in enumerate(r) if np.isfinite(v)}
            xy = tk.update(f"dev{trial}", o, i*dt)
            e.append(np.inf if xy is None else np.linalg.norm(xy - truth[i]))
            if i == len(obs)-1: sp.append(tk.spread(f"dev{trial}"))
        e = np.array(e)
        all_e.append(e[10:])          # regime, comparavel a bancada
        all_e0.append(e[:3])          # convergencia: 3 primeiros passos
    dur = time.perf_counter() - t0

    a, a0 = np.concatenate(all_e), np.concatenate(all_e0)
    a = a[np.isfinite(a)]; a0 = a0[np.isfinite(a0)]
    print(f"regime      mediana {np.median(a):5.2f} m   p90 {np.percentile(a,90):5.2f} m   "
          f"p99 {np.percentile(a,99):5.2f} m")
    print(f"convergencia (3 primeiros passos) mediana {np.median(a0):5.2f} m")
    print(f"incerteza publicada (spread final) mediana {np.median(sp):5.2f} m")
    print(f"custo {dur/10/len(truth)*1e3:.2f} ms/dispositivo/update  ->  "
          f"5000 dispositivos a cada 2 s = {5000*dur/10/len(truth)/2:.2f} nucleo")

    assert np.median(a) < 5.0, np.median(a)
    assert np.median(a0) < 6.0, f"convergencia ruim: {np.median(a0)}"

    # correcao 2: a verossimilhanca tem um termo por ancora que REPORTOU, nem mais
    # nem menos — e leitura nao-finita nao vira termo.
    tk2 = Tracker(anchors, fp, seed=0, sigma=SIGMA)
    assert tk2.loglik(fp.sample(50, rng), np.array([0, 1]), np.array([-60., -70.])).shape == (50, 2)
    tk2.update("filtra", {"anc0": -60.0, "anc1": None, "anc2": float("nan")}, 0.0)
    assert tk2.tracks["filtra"].n_upd == 1

    # correcao 3: vies de Ptx do alvo. Mesma trilha com +8 dB constante -> b_k acha
    # os 8 dB e o erro em regime nao piora.
    def corre_viesado(alfa):
        tk_ = Tracker(anchors, fp, seed=1, sigma=SIGMA, b_alfa=alfa)
        rb = np.random.default_rng(7)
        e_ = []
        for i, x in enumerate(truth):
            r = observe(x, rb) + 8.0                    # Ptx do alvo 8 dB acima do A
            o = {f"anc{j}": v for j, v in enumerate(r) if np.isfinite(v)}
            xy = tk_.update("viesado", o, i*2.0)
            if xy is not None and i >= 10:
                e_.append(np.linalg.norm(xy - truth[i]))
        return tk_, float(np.median(e_))

    _, sem = corre_viesado(0.0)
    tkb, com = corre_viesado(0.05)
    b = tkb.tracks["viesado"].b
    # b_k nao recupera os 8 dB inteiros: vies e posicao sao parcialmente o mesmo
    # parametro, e o equilibrio divide o offset entre os dois. O que tem de valer
    # e que ELE MELHORA o erro — e isso que este teste trava.
    # Nao se exige ganho: MEDIDO, nao ha. Exige-se que ligar nao estrague.
    assert com < sem + 0.2, f"b_k degradou: {com:.2f} m com, {sem:.2f} m sem"
    assert 2.0 < b < 12.0, f"b_k fora de faixa plausivel: {b:.1f}"
    print(f"b_k: alvo com +8 dB -> estimou {b:+.1f} dB; "
          f"regime {sem:.2f} m sem b_k -> {com:.2f} m com")
    tkb.fixa_vies("viesado", 0.0)
    assert tkb.tracks["viesado"].b == 0.0 and tkb.tracks["viesado"].b_fixo

    # correcao 4: saida primaria e o posterior por comodo, nao o metro
    post = tkb.comodo("viesado")
    assert abs(sum(post.values()) - 1.0) < 1e-6, post
    lado = "oeste" if truth[-1][0] < 20 else "leste"
    assert max(post, key=post.get) == lado, (post, truth[-1])
    print(f"comodo: posterior {[f'{k} {v:.2f}' for k, v in post.items()]} -> verdade {lado}")
    assert Tracker(anchors, Floorplan(WALLS, (0, 0, 40, 30))).comodo("x") == {}

    # ancora com z: rodape (0,30) contra alvo a 1,10 tem de dar distancia MAIOR que
    # a 2D, e (x, y) puro tem de continuar identico ao comportamento antigo.
    P1 = np.array([[3.0, 3.0]])
    a2d = {"a": (0.0, 3.0)}
    a3d = {"a": (0.0, 3.0, 0.30)}
    t2 = Tracker(a2d, fp, sigma=SIGMA)
    t3 = Tracker(a3d, fp, sigma=SIGMA, z_alvo=1.10)
    assert t2.z is None and t3.z is not None
    d2 = t2._dist(np.array([[3.0]]), np.array([0]))[0, 0]
    d3 = t3._dist(np.array([[3.0]]), np.array([0]))[0, 0]
    assert abs(d2 - 3.0) < 1e-9 and abs(d3 - np.hypot(3.0, 0.8)) < 1e-9, (d2, d3)

    # gancho do ganho por ancora (modelo/padrao.py): desligado tem de ser identico
    # ao de hoje, e ligado tem de deslocar o mu na medida exata do ganho — nem
    # mais nem menos, senao o teste de transferencia mediu outro modelo.
    tg = Tracker(a2d, fp, sigma=SIGMA, ganho=lambda P, ai, z: np.full((len(P), len(ai)), 2.0))
    r = np.array([-60.0])
    ll_sem = t2.loglik(P1, np.array([0]), r)[0, 0]
    ll_com = tg.loglik(P1, np.array([0]), r)[0, 0]
    assert abs(ll_com - t2.loglik(P1, np.array([0]), r - 2.0)[0, 0]) < 1e-9, (ll_com, ll_sem)
    assert t2.loglik(P1, np.array([0]), np.array([-60.0]))[0, 0] != \
           t3.loglik(P1, np.array([0]), np.array([-60.0]))[0, 0]
    # gancho temporal: desligado tem de ser IDENTICO ao de hoje; ligado, sigma
    # escala exatamente por escala(t) e mu desloca exatamente por mu(t).
    from rtls.modelo.temporal import Temporal, VIES_LOG
    ll0 = t2.loglik(P1, np.array([0]), r)[0, 0]
    assert t2.loglik(P1, np.array([0]), r, 0.0, 1.0)[0, 0] == ll0
    # K=0 e o modelo nulo: sigma constante, logo escala == 1 em qualquer hora —
    # ligar o gancho com ele nao pode mudar nada.
    tp = Temporal(0, np.zeros(0), np.array([2*np.log(2*SIGMA) + VIES_LOG]), ref=2*SIGMA)
    assert abs(tp.sigma(np.array([0.0]))[0] - 2*SIGMA) < 1e-9, tp.sigma(np.array([0.0]))
    assert abs(tp.escala(np.array([0.0]))[0] - 1.0) < 1e-12
    lls = t2.loglik(P1, np.array([0]), r, 0.0, 2.0)[0, 0]
    t4 = Tracker(a2d, fp, sigma=2*SIGMA)
    assert abs(lls - t4.loglik(P1, np.array([0]), r)[0, 0]) < 1e-9, (lls,)
    print(f"temporal: esc=2 identico a sigma dobrado ({lls:.4f}); esc=1 identico a hoje")

    print(f"z: ancora no rodape a 3,00 m no plano -> {d3:.2f} m reais "
          f"({10*2.8*np.log10(d3/d2):+.2f} dB de vies se ignorado)")

    # dispositivo com 1 ancora nao pode virar posicao confiante
    tk = Tracker(anchors, fp, seed=0, sigma=SIGMA)
    xy = tk.update("solo", {"anc0": -60.0}, 0.0)
    assert xy is not None and tk.spread("solo") > 5.0, tk.spread("solo")
    print(f"1 ancora -> posicao com spread {tk.spread('solo'):.1f} m (sinaliza incerteza, nao mente)")

    # sem ancora nenhuma e sem historico -> None, nao inventa
    assert Tracker(anchors, fp).update("nada", {}, 0.0) is None
    # expiracao
    tk.expire(1e6); assert not tk.tracks
    print("guardas: sem ancora -> None, expiracao ok")

if __name__ == "__main__":
    demo()
