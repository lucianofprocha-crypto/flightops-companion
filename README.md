# FlightOps Companion — Airport Intelligence

**App no ar:** https://flightops-companion.onrender.com (acessível de qualquer
lugar, celular incluso — hospedado no plano grátis do Render, pode levar
30-50s pra responder após período de inatividade).

Web app para consultar a climatologia de qualquer aeroporto do mundo
(temperatura, vento, visibilidade em metros e condições de voo
VFR/MVFR/IFR/LIFR) com base no histórico de observações METAR, além de ATIS
ao vivo quando disponível. Acessível pelo navegador, tanto no desktop quanto
no celular.

Este não é um modelo de previsão numérica (NWP): é uma **projeção
estatística** — "o que normalmente acontece neste aeroporto, nesta época e
horário, com base nos últimos 30 dias / 365 dias / 5 anos observados".

## Decisões tomadas nesta migração

O projeto original (ChatGPT) tinha só a interface esboçada em PySide6
(desktop), sem fonte de dados nem abordagem de previsão definidas. Para
colocar algo funcional de pé, decidi:

- **Arquitetura:** app web (FastAPI no backend + HTML/JS simples no
  frontend, sem framework pesado), já que você quer acesso por celular e
  desktop. O arquivo desktop original foi preservado em `legacy_desktop/`.
- **Fonte de dados:** [Iowa Environmental Mesonet (IEM)](https://mesonet.agron.iastate.edu/request/download.phtml) —
  arquivo histórico de METAR gratuito, sem API key, cobrindo aeroportos
  brasileiros (testado com SBGR). Se preferir outra fonte (CheckWX, AVWX,
  REDEMET etc.), o único arquivo a trocar é `backend/app/metar_client.py`.
- **Abordagem:** climatologia estatística — distribuição de categorias de
  voo, condições adversas por mês e por horário (UTC), a partir do histórico
  bruto. `backend/app/climatology.py` concentra essa lógica; é o lugar para
  evoluir para algo mais sofisticado (ex: modelos de série temporal) no
  futuro.
- **ICAO livre:** o app aceita qualquer código ICAO de 4 letras (não só os 5
  aeroportos originais). A cobertura de dados depende do IEM Mesonet —
  aeroportos pequenos/sem estação automatizada podem não ter histórico (o app
  avisa de forma amigável nesse caso).
- **ATIS ao vivo:** integrado via [atis.info](https://atis.info) (D-ATIS
  digital da FAA, gratuito, sem API key). Cobertura é praticamente só EUA —
  fora de lá, o card de ATIS simplesmente não aparece (não é tratado como
  erro). `backend/app/atis_client.py`.
- **NOTAM (fonte oficial):** ainda não integrado. A fonte planejada é a API
  AISWEB do DECEA (oficial, cobre NOTAM/METAR/TAF/cartas para o espaço aéreo
  brasileiro) — chave de API já solicitada, pendente de aprovação. Quando
  chegar, ativar em `backend/app/notam_client.py` (a criar) seguindo o mesmo
  padrão de `metar_client.py`.
- **Leitura de flight briefing (PDF):** upload de PDF de despacho (ex:
  ForeFlight) com extração automática dos pontos de atenção. Implementado em
  `backend/app/briefing_parser.py`: localiza a página de METAR/TAF/SIGMET
  (classifica cada aeroporto em VFR/SVFR/IFR a partir de visibilidade e teto)
  e as páginas de NOTAM (mesmo em layout de 2 colunas), mas só destaca
  fechamentos de pista, táxi e aeródromo/aeroporto — deduplicados quando
  repetitivos e marcados como vigentes ou não no momento. É uma leitura
  "melhor esforço" para o formato observado nos briefings do ForeFlight —
  não substitui a conferência do PDF original, que continua disponível junto
  de cada ponto extraído.
- **Comparação de rota:** a página "ICAO FLIGHT PLAN" do PDF é lida para
  extrair a rota (campo 15) e demais dados do plano de voo. Colando no campo
  opcional o texto do "plano apresentado" (mensagem do despachante com o
  STRIP do FPL), o app compara as duas rotas waypoint a waypoint (diff) e
  também verifica os itens de coordenação: atendimento confirmado na
  origem/destino, FPL aprovado, FPL OK, slots e PPR.
- **Comparação de documentos de tripulação/passageiros (GEDEC, eAPIS,
  eGAR, lista de passageiros):** `backend/app/travel_docs_parser.py` lê os
  quatro documentos e cruza nome, nacionalidade, número de documento e
  data de nascimento de cada pessoa entre eles, apontando divergências
  (ex: passaporte diferente usado em um dos formulários) e quem está
  ausente em algum documento. GEDEC, eAPIS e a lista de passageiros têm
  texto extraível normalmente (a lista de passageiros costuma vir com
  páginas extras de fotos de passaporte escaneadas — só a primeira página,
  com a tabela, é lida). O eGAR (Reino Unido) é gerado via "imprimir em
  PDF" do navegador e não tem texto embutido — os dados dele vêm de
  **OCR** (pytesseract sobre a página renderizada, reconstruindo a tabela
  por posição das colunas). Por depender de OCR, o campo
  `document_number` do eGAR pode confundir caracteres parecidos (ex:
  `0`/`O`, `1`/`I`); toda pessoa vinda do eGAR é marcada com `"ocr": true`
  e o app avisa na tela pra conferir visualmente o PDF original quando uma
  divergência envolver o eGAR.
- **Relatório de pré-voo em PDF (Fase 1):** botão "GERAR RELATÓRIO PDF" que
  consolida num único PDF o que já foi analisado na página — meteorologia
  VFR/SVFR/IFR, NOTAMs de fechamento, comparação de rota + checklist de
  coordenação e a comparação de documentos de tripulação/passageiros.
  Implementado em `backend/app/report_generator.py` (reportlab), servido
  por `POST /api/report/generate`. O frontend só reenvia o JSON que os
  outros endpoints já devolveram — nenhum PDF é relido. **Fase 1** é só
  texto/tabelas: não inclui o mapa da rota nem dados de combustível,
  tripulação e alternados da capa do briefing (fica pra uma fase futura).

## Estrutura

```
backend/
  app/
    main.py          # API FastAPI + serve o frontend
    metar_client.py  # busca histórico no IEM Mesonet
    climatology.py   # cálculo das estatísticas
    atis_client.py   # ATIS ao vivo (atis.info, cobertura EUA)
    briefing_parser.py    # leitura/resumo de PDF de flight briefing
    travel_docs_parser.py # comparação de GEDEC/eAPIS/eGAR
    report_generator.py   # relatório de pré-voo em PDF (Fase 1)
  requirements.txt
frontend/
  index.html
  app.js
  styles.css
legacy_desktop/
  main.py            # protótipo original em PySide6 (Qt), mantido como referência
Dockerfile           # deploy (ver "Deploy" abaixo — precisa de Docker por causa do OCR)
```

## Como rodar

A leitura do eGAR usa OCR (`pytesseract`), que depende do binário
`tesseract-ocr` do sistema — instale antes de rodar localmente:

```bash
brew install tesseract        # macOS
# ou: apt-get install tesseract-ocr   # Linux
```

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Acesse no navegador do computador: **http://localhost:8000**

## Acessar pelo celular

O celular precisa estar na **mesma rede Wi-Fi** do computador.

1. Descubra o IP local do computador:
   - macOS: `ipconfig getifaddr en0` (ou `en1` se usar Wi-Fi em outra interface)
   - Windows: `ipconfig` (procure "Endereço IPv4")
   - Linux: `hostname -I`
2. No celular, abra o navegador em `http://<esse-IP>:8000` (ex:
   `http://192.168.0.15:8000`).
3. Se não carregar, confira o firewall do computador — ele pode estar
   bloqueando conexões na porta 8000.

Isso só é necessário rodando localmente. Pra acesso de qualquer lugar, use o
link em produção no topo deste README — já está no ar via Render, deploy
automatizado pelo `render.yaml` na raiz do repositório.

## Deploy

O deploy no Render usa **Docker** (`Dockerfile` na raiz), não o runtime
nativo Python — o runtime nativo do Render não inclui o binário
`tesseract-ocr` necessário pra leitura do eGAR, e não há como instalar
pacotes de sistema nele. O Dockerfile instala o `tesseract-ocr` via
`apt-get` antes de instalar as dependências Python. Isso deixa o build um
pouco mais lento que antes (imagem Docker do zero), mas o restante do fluxo
de deploy é o mesmo (push pro GitHub, Render redeploya automaticamente).

## Próximos passos sugeridos

- **NOTAM (fonte oficial)**: chave da API AISWEB (DECEA) já solicitada,
  pendente de aprovação. Quando chegar, integrar em
  `backend/app/notam_client.py` seguindo o padrão de `metar_client.py` — vai
  complementar (não substituir) a leitura de PDF acima, trazendo NOTAM
  atualizado na hora em vez de depender de um briefing já gerado.
- Persistir os dados buscados (hoje o cache é só em memória e expira em 1h).
- **Relatório em PDF — Fase 2**: replicar o "sketch" visual completo (mapa
  de rota com FIRs coloridos, combustível, tripulação/SOB e alternados),
  o que exige (a) ler a capa do briefing (esses dados ainda não são
  extraídos por `briefing_parser.py`) e (b) uma forma de desenhar o mapa —
  `cartopy`/`geopandas` não estão disponíveis no ambiente atual, então
  provavelmente via dados de fronteiras leves + `matplotlib`.
- **Checklist geral de pré-voo**: lista consolidada de todos os itens que
  devem ser verificados antes de cada voo (além dos já cobertos pela
  comparação de rota).
