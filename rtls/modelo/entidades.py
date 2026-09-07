"""Taxonomia de entidades de RF do sitio: as variaveis descritivas de cada uma.

Uma ENTIDADE e qualquer coisa que emite, recebe ou ATRAPALHA radio. As tres coisas
sao a mesma lista de proposito: no modelo, um armario e uma ancora sem radio, e uma
ancora e um armario que fala. Foi essa unificacao que o operador pediu com "cada um
desses no espaco altera a relacao de todos os outros".

Cada entidade carrega quatro blocos de variaveis:

  GEOMETRIA   pos (x,y,z) em metros na planta;  R = (yaw, pitch, roll) em graus,
              a orientacao do CORPO. O padrao de antena mora no referencial do
              corpo, entao girar a placa gira o padrao — e so isso que o giro
              medido em 05/09 (10,2 dB na a4) mexeu.

  CADEIA      p_tx (dBm comandado, conhecido), t (offset da cadeia de TX, dB) e
              r (offset da cadeia de RX, dB). t e r sao SEPARADOS de proposito:
              o PA e o LNA sao circuitos diferentes e nao sao reciprocos. A
              antena e reciproca e entra nos dois sentidos; a cadeia nao.

  ANTENA      n_ant, combinacao (uma so / selecao / soma de potencia), pol (eixo
              de polarizacao no referencial do corpo) e c = coeficientes do padrao
              numa base de harmonicos esfericos de media zero. c e o que a campanha
              mede e o que o offset escalar reprovado tentava resumir num numero.

  CORPO       raio, altura e B = atenuacao em dB quando o corpo tapa o enlace por
              inteiro. E por aqui que a entidade entra nos enlaces DOS OUTROS.

Nada aqui e chute solto: os defaults vem de medicao registrada no projeto
(ver o campo `fonte` de cada tipo).
"""
from dataclasses import dataclass, field
import numpy as np

# ---------------------------------------------------------------- combinacao
UMA, SELECAO, SOMA = "uma", "selecao", "soma"

@dataclass
class Entidade:
    nome: str
    tipo: str
    pos: tuple                      # (x, y, z) m, planta (y cresce para BAIXO)
    R: tuple = (0.0, 0.0, 0.0)      # yaw, pitch, roll em graus
    # --- cadeia
    p_tx: float = 0.0               # dBm comandado (conhecido)
    t: float = 0.0                  # offset da cadeia de TX (dB, a estimar)
    r: float = 0.0                  # offset da cadeia de RX (dB, a estimar)
    # --- antena
    n_ant: int = 1
    combinacao: str = UMA
    pol: tuple = (0.0, 0.0, 1.0)    # eixo do dipolo no referencial do corpo
    grau: int = 1                   # grau maximo dos harmonicos do padrao
    c: np.ndarray = None            # coeficientes do padrao (dB), media zero
    ganho_nom: float = 0.0          # ganho de pico nominal (dBi), so informativo
    # --- corpo
    raio: float = 0.03
    altura: float = 0.06
    B: float = 0.0                  # dB de atenuacao com o enlace tapado
    # --- papel
    tx: bool = True
    rx: bool = True
    movel: bool = False
    fonte: str = ""

    def __post_init__(self):
        if self.c is None:
            self.c = np.zeros(n_coef(self.grau))
        self.pos = tuple(float(v) for v in self.pos)

    @property
    def xyz(self):
        return np.array(self.pos, float)

    @property
    def M(self):
        """Matriz de rotacao corpo->planta (yaw em torno de z, depois pitch, roll)."""
        y, p, r_ = np.radians(self.R)
        cz, sz = np.cos(y), np.sin(y)
        cy, sy = np.cos(p), np.sin(p)
        cx, sx = np.cos(r_), np.sin(r_)
        Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
        Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
        return Rz @ Ry @ Rx


def n_coef(grau):
    """Numero de harmonicos esfericos reais de grau 1..L (o grau 0 fica de fora:
    ele e a constante, que ja e o t/r — deixar os dois seria matriz singular)."""
    return (grau + 1) ** 2 - 1


# ------------------------------------------------------------------ catalogo
# Defaults por TIPO. O que muda de individuo para individuo (posicao, giro,
# potencia) vem do chamador; o que e do modelo da placa mora aqui.
CATALOGO = {
    "ap": dict(n_ant=4, combinacao=SELECAO, ganho_nom=2.0, grau=2,
               raio=0.09, altura=0.15, B=6.0,
               fonte="roteador domestico 4 antenas; T1 le -64 dBm dele atraves de 4 paredes"),
    "c3_com_antena": dict(n_ant=1, combinacao=UMA, ganho_nom=0.0, grau=2,
                          raio=0.02, altura=0.10, B=2.0,
                          fonte="SuperMini Plus + u.FL (jumper 0R soldado). a1, a2, a4 em 05/09"),
    "c3_sem_antena": dict(n_ant=1, combinacao=UMA, ganho_nom=-20.0, grau=2,
                          raio=0.02, altura=0.02, B=2.0,
                          fonte="antena ceramica CA-C03 colada no plano de terra: -16 a -24 dBi medidos"),
    "cyd": dict(n_ant=1, combinacao=UMA, ganho_nom=-6.0, grau=2,
                raio=0.05, altura=0.09, B=8.0,
                fonte="ESP32 classico com LCD; o fundo metalico da tela faz o padrao. Giro de 05/09: 10,2 dB"),
    "mini_teclado": dict(n_ant=1, combinacao=UMA, ganho_nom=-10.0, grau=1,
                         raio=0.04, altura=0.01, B=3.0,
                         fonte="teclado BLE; antena de trilha sob o plano de terra do teclado"),
    "tembed": dict(n_ant=1, combinacao=UMA, ganho_nom=-4.0, grau=2,
                   raio=0.04, altura=0.08, B=6.0,
                   fonte="T-Embed S3. So escuta neste projeto."),
    "pessoa": dict(n_ant=0, combinacao=UMA, ganho_nom=0.0, grau=0,
                   raio=0.20, altura=1.75, B=20.0, tx=False, rx=False, movel=True,
                   fonte="MEDIDO 04/09: de pe na a1, a a6 apareceu com 9 pkt/min num enlace morto e sumiu ao sair"),
    "movel": dict(n_ant=0, combinacao=UMA, grau=0, raio=0.30, altura=1.80,
                  B=4.0, tx=False, rx=False,
                  fonte="armario/geladeira: obstaculo puro, sem radio"),
}


def cria(nome, tipo, pos, **kw):
    d = dict(CATALOGO[tipo]); d.update(kw)
    return Entidade(nome=nome, tipo=tipo, pos=pos, **d)


def cena(P=None):
    """A cena do SITIO: cada ancora e cada emissor fixo do JSON vira uma Entidade.

    O que o JSON tem de dizer, alem da posicao, e `tipo` (qual linha do CATALOGO)
    e `yaw` (para onde o CORPO aponta). O yaw nao e cosmetico: o padrao de antena
    mora no referencial do corpo, entao girar a placa gira o padrao — foi so isso
    que o giro medido em 05/09 (10,2 dB numa ancora) mexeu. Se voce nao souber o
    yaw, ponha o da parede em que a placa esta parafusada, com a antena para
    dentro do comodo, e anote que e estimativa.
    """
    if P is None:
        from rtls import sitio as P
    ents = {}
    for tag, meta in P.D["ancoras"].items():
        if meta.get("radio") is None:
            continue                                  # posicao candidata, sem placa
        num = str(meta["radio"])
        ents[num] = cria(num, meta.get("tipo", "c3_sem_antena"), tuple(meta["pos"]),
                         R=(float(meta.get("yaw", 0.0)), 0, 0),
                         p_tx=float(meta.get("p_tx_dBm", 9.0)))
    for nome, meta in P.D.get("emissores_fixos", {}).items():
        tipo = meta.get("tipo_rf", "movel")
        ents[nome] = cria(nome, tipo, tuple(meta["pos"]),
                          **{k: v for k, v in meta.items()
                             if k in ("p_tx", "tx", "rx")})
    return ents


def demo():
    e = cria("x", "cyd", (1.0, 2.0, 0.75), R=(90, 0, 0))
    assert e.c.shape == (n_coef(2),) == (8,)
    v = e.M @ np.array([1.0, 0, 0])
    assert np.allclose(v, [0, 1, 0], atol=1e-9), v          # yaw 90 leva x em y
    assert np.allclose(e.M @ e.M.T, np.eye(3), atol=1e-12)
    from rtls import sitio as P
    ents = cena()
    assert len(ents) == len(P.ESCOLHIDAS) + len(P.EMISSORES), sorted(ents)
    assert all(str(n) in ents for n in P.INSTALADO.values())
    # O sitio pode nao ter emissor fixo nenhum. Se tiver um do tipo "ap", ele tem de
    # herdar o catalogo (4 antenas, selecao) — e isso que prova que cena() le o JSON
    # e nao inventa. Citar o NOME de um emissor de um sitio especifico seria a
    # mesma armadilha que ja quebrou campanha/loo/nuvem em outro sitio.
    aps = [e for e in ents.values() if e.tipo == "ap"]
    assert all(e.n_ant == 4 and e.combinacao == SELECAO for e in aps), aps
    print("entidades ok:", " ".join(f"{k}:{v.tipo}" for k, v in ents.items()))

if __name__ == "__main__":
    demo()
