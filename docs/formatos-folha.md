# Formatos de folha Gromar (.slddrt)

Gerados por `tools/gerar_formatos_gromar.py`, inspirados no padrão do desenho-cobaia
do cliente HINE (`9-8126.A.pdf`), porém em português e com o logo Gromar.

## O que cada folha tem

- Moldura ISO 5457: margem de 20 mm à esquerda (arquivamento) e 10 mm nos demais lados.
- Faixa de zonas alfanumérica (letras de cima para baixo, números da esquerda para a
  direita) nos quatro lados — **exceto A4**, que a norma dispensa e onde ela roubaria
  a largura da legenda.
- Marcas de centro nos quatro lados.
- Revisão dentro da própria legenda (REV. / DATA REV. / NOME) — sem tabela solta no
  topo da folha. Mostra a revisão corrente, não o histórico.
- Legenda de 180 × 62 mm no canto inferior-direito, com símbolo de projeção em
  1º diedro e o logo Gromar.

| Arquivo | Folha | Zonas |
|---|---|---|
| `A4 - retrato - gromar.slddrt` | 210 × 297 | — |
| `A4 - paisagem - gromar.slddrt` | 297 × 210 | — |
| `A3 - gromar.slddrt` | 420 × 297 | 6 × 4 |
| `A2 - gromar.slddrt` | 594 × 420 | 8 × 6 |
| `A1 - gromar.slddrt` | 841 × 594 | 12 × 8 |
| `A0 - gromar.slddrt` | 1189 × 841 | 16 × 12 |

Instalados em
`C:\ProgramData\SolidWorks\SOLIDWORKS 2023\lang\portuguese-brazilian\sheetformat\Gromar`
— uma pasta só nossa, e a preferência `swFileLocationsSheetFormat` aponta para ela.
Assim a caixa "Formato/tamanho da folha" lista **apenas** os seis formatos Gromar,
sem risco de alguém pegar um `a3 - iso` por engano. Os formatos nativos continuam
intactos na pasta acima; para voltar a enxergá-los, devolva a preferência a
`...\portuguese-brazilian\sheetformat` (Ferramentas → Opções → Locais de arquivo →
Formatos de folha).

## Campos e de onde vêm

Do **modelo** referenciado pela vista (`$PRPSHEET`):

| Campo na legenda | Propriedade |
|---|---|
| MATERIAL | `MATERIAL` |
| PESO (kg) | `SW-Mass` (massa calculada) |
| TÍTULO | `DESCRICAO` |

Do **desenho** (`$PRP` — propriedades personalizadas do .slddrw):

| Campo na legenda | Propriedade |
|---|---|
| NOTA / Tol. geral | `TOLERANCIA GERAL` |
| TRATAM. | `TRATAMENTO` |
| DESENHADO | `DESENHADO` (já vem "Rafael" nos templates desta máquina) |
| APROVADO / DATA | `APROVADO`, `DATA APROVACAO` |
| Nº OS | `OS` |
| REV. (nos dois lugares) | `Revisão` — nome fixado pelo SolidWorks (`swDrawingCustomPropertyUsedAsRevision`) |
| NOME (da revisão) | `NOME REVISAO` (já vem "Rafael") |

Datas que o SolidWorks preenche sozinho:

| Campo | Fonte | Comportamento |
|---|---|---|
| DATA (do desenho) | `SW-Created Date` | data em que o arquivo nasceu — fixa |
| DATA REV. | `SW-Last Saved Date` | data da última gravação — anda a cada save |
| DATA (do aprovado) | `DATA APROVACAO` | manual: aprovação é ato humano |

Os campos `SW-Short Date`/`SW-Long Date` foram descartados: parecem estáticos mas
mostram sempre a data de **hoje**, então o papel registraria quando foi aberto, não
quando foi feito. Para as datas caberem na célula, o formato de data longa do Windows
(`HKCU:\Control Panel\International\sLongDate`) foi mudado de
`dddd, d' de 'MMMM' de 'yyyy` para `dd/MM/yyyy` — reverta ali se precisar do formato
por extenso em outros programas. A hora vem junto (`26/08/2026 20:19:19`) e só sairia
mexendo no formato de hora do sistema, o que afeta o relógio.

Preenchidos pelo próprio SolidWorks: ESCALA, Nº DESENHO e ARQUIVO CAD (nome do
arquivo), FOLHA x DE y. O campo FORMATO é texto fixo em cada folha.

O SolidWorks não tem cadastro de usuário (isso é do PDM) — nenhum campo de nome se
preenche sozinho. Por isso o nome do desenhista fica fixo no template, em
`PROPRIEDADES` (`tools/gerar_templates_gromar.py`): `DESENHADO` e `NOME REVISAO` já
nascem com "Rafael". Troque os valores e regere se a máquina mudar de dono.

A tabela de revisão nativa foi testada e removida a pedido: ela preenchia letra e
data sozinha, mas ficava solta no topo da folha. Se um dia o histórico de revisões
for necessário, o caminho está no histórico do git (`ISheet::InsertRevisionTable2`
com âncora `swTableAnnotation_RevisionBlock` gravada no formato).

## Logo

`assets/logo-gromar.png` é o logo oficial com o fundo recortado, gerado por
`tools/logo_transparente.py` a partir do JPG da pasta Comercial. O JPG não tem canal
alfa e entrava na legenda como um retângulo branco.

O recorte é um flood fill a partir dos quatro cantos: só sai o branco **conectado à
borda**, então os miolos vazados das letras (o "o", o "g") continuam brancos e opacos
— o que é o correto sobre folha branca. Regere com:

```
python tools/logo_transparente.py
```

## Templates de desenho (.drwdot)

`tools/gerar_templates_gromar.py` cria, em
`C:\ProgramData\SolidWorks\SOLIDWORKS 2023\templates`, um template por formato
(`Desenho A3 - Gromar.drwdot` etc.) já com o `.slddrt` aplicado, folha na escala
1:1 em primeiro diedro, unidades em mm e as propriedades da legenda criadas
vazias — o desenhista só preenche.

O **A3 é o template padrão do SolidWorks**: "Novo desenho" já abre nele. Para
trocar o padrão para outro formato:

```
python tools/gerar_templates_gromar.py --padrao a4        # ou a0/a1/a2/a4v
python tools/gerar_templates_gromar.py --sem-definir-padrao
```

O padrão anterior era `templates\Desenho.drwdot`, que continua na pasta.

## Preferências ajustadas na máquina

| Preferência | Valor | Efeito |
|---|---|---|
| `swAlwaysUseDefaultTemplates` | `False` | "Novo documento" pergunta qual template usar (modo **Avançado** do diálogo lista os seis) |
| `swDrawingShowSheetFormatDialog` | `True` | Ao criar o desenho aparece a caixa "Formato/tamanho da folha" para escolher A4/A3/… |
| `swFileLocationsSheetFormat` | `...\sheetformat\Gromar` | Essa caixa lista só os formatos Gromar |
| `swDefaultTemplateDrawing` | `Desenho A3 - Gromar.drwdot` | Usado pelo que não pergunta (ex.: desenho a partir do modelo via API) |

## Regerar

```
python tools/gerar_formatos_gromar.py --dest "<pasta>"          # os seis
python tools/gerar_formatos_gromar.py --only a3 --dest "<pasta>" --manter-aberto
python tools/gerar_templates_gromar.py                          # refaz os .drwdot
```

Ao mexer no layout, regere os `.slddrt` **e** os `.drwdot`: o template carrega
uma cópia do formato, não um link vivo.

Detalhes de API que o gerador precisa respeitar (todos custaram tentativa e erro):

- `ISheet::SaveFormat` grava o `.slddrt`; `IModelDoc2::SaveAs2` com essa extensão
  retorna sucesso e **não grava arquivo nenhum**.
- `INote`, `IAnnotation`, `ITextFormat` e `ISketchPicture` exigem `cast_to` — o
  dispatch dinâmico não expõe os membros dessas interfaces.
- `IAnnotation::SetPosition` ancora a nota pelo topo: a base do texto cai
  ~1,13 × `CharHeight` abaixo do ponto informado.
- Com `SketchManager.AddToDB = False` o SolidWorks infere relações e deforma o
  traçado (o símbolo de projeção sai torto).
- `InsertSketchPicture` deixa uma linha de centro solta no sketch, que precisa ser
  removida depois — senão ela aparece atravessando a legenda no desenho.
- `IModelDoc2::SaveAs2` grava o `.drwdot` mas devolve `False`; confira o arquivo
  em disco (mtime), não o retorno.
- Objeto de tabela recuperado da árvore de features é um `IRevisionTableFeature`;
  as anotações saem de `GetTableAnnotations()` e exigem `QueryInterface` de verdade
  (o `cast_to`, que só reaproveita o ponteiro, devolve "Member not found").
- A altura do texto da tabela é gravada célula a célula (`SetCellTextFormat`);
  `SetTextFormat` na tabela e a preferência de documento não têm efeito.
- A primeira linha do cabeçalho (título) não pode ser removida — `DeleteRow(0)`
  devolve `False`. Por isso ela virou "HISTÓRICO DE REVISÕES".
