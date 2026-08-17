# Paleta e tipografia compartilhadas entre overlay, painel e ícone de bandeja.
# Identidade "Tactile Peach" (neumorphism) — vinda do design system gerado
# no Stitch para o projeto "Peach Voice Studio" e adaptada aqui para os
# estados/telas reais do GeniusPeach.

# Superfícies (todas as superfícies neumórficas usam a MESMA cor de fundo —
# a profundidade vem só da dupla sombra clara/escura, nunca de um tom de
# preenchimento diferente).
SURFACE = "#f9f9f9"
SURFACE_CONTAINER_LOWEST = "#ffffff"
SURFACE_CONTAINER_LOW = "#f4f3f3"
SURFACE_CONTAINER = "#eeeeee"
SURFACE_CONTAINER_HIGH = "#e8e8e8"
SURFACE_CONTAINER_HIGHEST = "#e2e2e2"
SURFACE_DIM = "#dadada"

ON_SURFACE = "#1a1c1c"
ON_SURFACE_VARIANT = "#52443c"
OUTLINE = "#85736b"
OUTLINE_VARIANT = "#d7c2b9"

PRIMARY = "#89502e"
ON_PRIMARY = "#ffffff"
PRIMARY_CONTAINER = "#ffb38a"
ON_PRIMARY_CONTAINER = "#794323"

SECONDARY = "#74593f"
SECONDARY_CONTAINER = "#fed9b8"
ON_SECONDARY_CONTAINER = "#795d43"

ERROR = "#ba1a1a"
ERROR_CONTAINER = "#ffdad6"
ON_ERROR = "#ffffff"

# Par de sombras do neumorphism (clara no canto superior-esquerdo, escura no
# inferior-direito) — os mesmos tons usados no box-shadow gerado no Stitch.
SHADOW_LIGHT = "#ffffff"
SHADOW_DARK = "#bebebe"

# Cores "por estado" ficam dentro da própria família da paleta (peach para
# tudo que está ativo/em progresso, marrom profundo pra concluído, vermelho
# só pro erro) — o design é propositalmente quase monocromático, então quem
# diferencia os estados é o ícone/animação/rótulo, não um arco-íris de cores.
STATE_IDLE = OUTLINE
STATE_LISTENING = PRIMARY_CONTAINER
STATE_TRANSCRIBING = PRIMARY_CONTAINER
STATE_OPTIMIZING = SECONDARY_CONTAINER
STATE_DONE = PRIMARY
STATE_ERROR = ERROR

FONT_FAMILY = "Hanken Grotesk"
FONT_FAMILY_FALLBACK = "Segoe UI"

# Raios usados nos cartões/pills neumórficos (mesma escala do design.md).
RADIUS_SM = 6
RADIUS_MD = 12
RADIUS_LG = 20
RADIUS_XL = 32
