# Detalhes do projeto — Card Scanner TCG

Documento do Scanner, consolidado a partir do código, README.md e CardeScanner.md existentes. Desenvolvido por Giovani Oliveira.

## 1. Objetivo

Aplicativo em Python para ler cards Pokémon por fotografia ou webcam, identificar a edição, organizar múltiplas listas de cards e exportar essas listas para Pokémon TCG Live / Limitless ou para a procura de cartas da Liga Pokémon.

O processamento de OCR acontece no computador. O usuário opera uma interface web pelo navegador, normalmente em `http://127.0.0.1:5000`.

Este documento descreve exclusivamente o CardScanner. O projeto TCG Overlay e seus componentes não fazem parte desta aplicação.

## 2. Plataforma e tecnologias

| Tecnologia | Responsabilidade |
| --- | --- |
| Python | Execução da aplicação e processamento local. |
| Flask | Interface HTTP, recebimento das imagens e API. |
| Waitress | Servidor utilizado pelos scripts de inicialização. |
| Pillow e NumPy | Preparação das imagens. |
| RapidOCR e ONNX Runtime | Extração de texto usando CPU. |
| RapidFuzz | Comparação dos nomes reconhecidos com o catálogo. |
| Requests e TCGdex | Consultas a cards e coleções. |
| SQLite | Persistência de listas, quantidades e tokens de inclusão. |
| HTML, CSS e JavaScript | Interface, controles e captura pelo navegador. |
| QR code | Acesso ao modo opcional de rede pelo celular. |
| unittest e Playwright | Testes de serviços, API e interface. |

A instalação é voltada ao Windows, com Python 3.11 a 3.13 de 64 bits. A documentação existente registra desenvolvimento e verificação com Python 3.13.

## 3. Leitura por arquivo de foto

O usuário seleciona uma imagem e visualiza sua prévia antes de iniciar a leitura. Existe uma opção de girar a imagem; a preparação também corrige a orientação EXIF.

O navegador reduz a imagem antes do envio. O servidor recebe a foto, prepara os pixels e executa o OCR. O limite de upload configurado é de 12 MB.

O fluxo recomendado é apresentar um card de frente, na vertical, sem cortar nome ou rodapé. Uma imagem legível deve permitir identificar nome, número e coleção.

As fotografias são processadas em memória: não são armazenadas em disco nem enviadas ao catálogo TCGdex.

## 4. Webcam e câmera do celular pelo Windows

O modo Usar webcam solicita permissão de vídeo ao navegador, sem solicitar microfone. O seletor apresenta as entradas de vídeo que o navegador e o Windows disponibilizam, incluindo webcams integradas, USB e virtuais.

É possível atualizar a lista de dispositivos, trocar a câmera, fazer uma captura única ou iniciar leitura contínua. A troca libera a câmera anterior; desligar ou retornar ao modo de arquivo também libera o dispositivo.

A câmera do celular pode ser usada quando o Windows a disponibiliza como câmera conectada. O vínculo, a compatibilidade e as permissões precisam ser configurados no próprio Windows. O Scanner utiliza a câmera como uma entrada comum do navegador; não implementa um aplicativo de celular ou o vínculo entre dispositivos.

A captura por webcam utiliza a área delimitada pela moldura. O nome e a numeração do card devem permanecer visíveis nessa região.

O acesso por `127.0.0.1` ou `localhost` permite o contexto local apropriado para a API de câmera. A câmera pode continuar indisponível quando bloqueada pelo navegador, sistema ou política do computador.

## 5. Leitura contínua, pausa e bip

O modo contínuo realiza uma captura, aguarda seu processamento e inclusão e só então agenda o próximo ciclo. A pausa padrão é de 2,5 segundos, com opções de 2 ou 3 segundos. O tempo de OCR e de consultas é adicional à pausa.

A inclusão automática é ativada nesse modo. Um bip confirma uma nova inclusão salva na lista. Não há bip de inclusão quando o resultado é ambíguo ou bloqueado pela proteção de repetição. O som pode ser testado ou desativado.

A proteção Evitar contar novamente o mesmo card parado vem ativada. Para registrar outra cópia da mesma edição, o usuário pode retirar o card e aguardar Área livre, obtida após duas leituras sem texto, antes de reapresentá-lo. Também pode desativar essa proteção para somar a cada ciclo.

Essa verificação depende do OCR e não constitui uma detecção visual garantida de área vazia. Reflexos ou texto ilegível podem afetar seu funcionamento.

Parar encerra o ciclo e mantém a prévia. Uma inclusão já enviada pode terminar, mas nenhuma captura adicional é agendada. Sair da aba pausa a leitura contínua. Falhas de conexão ou inclusão também pausam o ciclo para conferência. Lista, idioma e quantidade ficam travados durante a leitura contínua.

## 6. Identificação de cards e consulta manual

O reconhecimento cruza o nome na região superior com dados do rodapé, como número da carta, fração e código da coleção. O suporte disponível é para português e inglês, sujeito à cobertura do TCGdex.

Uma fração completa pode identificar uma única coleção mesmo sem código legível. Promocionais com código e número sem fração também são considerados.

A inclusão automática exige que a edição seja resolvida. Ambiguidade, ausência de dados ou conflitos entre código e numeração impedem uma escolha automática e deixam candidatos para conferência manual.

A tela apresenta até 12 candidatos. A identificação considera os candidatos compatíveis antes de limitar a lista exibida.

A busca manual aceita nome e número e pode filtrar por coleção; o filtro de coleção exige também o número. O usuário pode abrir detalhes e adicionar a edição escolhida à lista.

Se o catálogo estiver indisponível, o texto extraído continua sendo apresentado. As sugestões não garantem identificação correta; a imagem, edição e quantidade devem ser conferidas.

## 7. Múltiplas listas e edição de quantidades

O sistema permite criar, selecionar, renomear e apagar listas. A primeira utilização cria Minha lista. O navegador lembra a última lista selecionada, que recebe as próximas inclusões.

Apagar lista pede confirmação com o nome e a quantidade. Somente a lista selecionada e seus itens são removidos. Outra lista é selecionada; quando a última é apagada, o sistema cria uma nova Minha lista vazia.

Cópias por leitura determina a quantidade adicionada a cada reconhecimento. Leituras da mesma edição somam ao item existente.

A quantidade pode ser digitada diretamente e salva com Enter ou ao sair do campo. Esc cancela a edição ainda não salva. Também existem os botões +, − e Remover. Os valores aceitos são inteiros de 0 a 999; zero remove o item.

Não são impostos os limites competitivos de quatro cópias ou de 60 cards. As listas servem para coleções e decks em construção.

A edição de quantidade mantém a posição da rolagem. Novas inclusões recebem destaque e são trazidas para a área visível, facilitando o acompanhamento da câmera.

Tokens persistidos evitam que a repetição de uma requisição some a mesma leitura novamente na mesma lista. Repetir Ler na mesma foto não adiciona novamente; selecionar o arquivo outra vez inicia uma nova leitura. Essa proteção é distinta da verificação do card parado na webcam.

## 8. Exportação TCG Live / Limitless

A interface apresenta uma única opção para TCG Live / Limitless. O texto contém quantidade, nome em inglês, código da coleção e número, organizado nas categorias Pokémon, Trainer e Energy, seguido do total de cópias.

```text
Pokémon: 1
2 Charizard ex OBF 125

Total Cards: 2
```

O número no cabeçalho da categoria representa entradas distintas; o total representa cópias. Componentes inteiramente numéricos da numeração são exportados sem zeros iniciais nesse formato. Prefixos como TG são preservados.

O código é obtido de tcgOnline ou da abreviação oficial da coleção. Energias básicas usam a representação com símbolos, como Basic {L} Energy.

Quando faltam nome em inglês, categoria, código ou outros dados obrigatórios, a exportação informa o problema em vez de inventar dados. O importador do TCG Live deve estar configurado em inglês.

O arquivo pode ser baixado em .txt ou copiado. O aplicativo não envia a lista ao jogo ou a plataformas externas e não comprova legalidade nem disponibilidade da edição nesses serviços.

## 9. Exportação Liga Pokémon

O formato para procura de cartas gera uma linha por edição, sem cabeçalhos, código da coleção ou total da lista:

```text
4 Dragapult ex (130/167)
1 Mienfoo (052/086)
1 Jett (079/084)
1 Nome da carta (001/005)
4 Binacle (087/∞)
```

O nome utilizado é o nome em inglês. Para coleções comuns, o denominador é o total oficial impresso da coleção, permitindo também cartas secretas, como 223/197.

Números inteiramente numéricos são preenchidos até pelo menos três dígitos. Zeros já presentes e números maiores são preservados. Portanto, 001/005 permanece 001/005. Prefixos alfanuméricos são mantidos.

Coleções identificadas como promocionais pelo catálogo recebem infinito no denominador, mesmo se o cadastro possuir um total numérico. A numeração original da carta é preservada, como no exemplo Binacle (087/∞).

Listas antigas podem receber os metadados necessários na exportação usando catálogo ou cache, sem substituir quantidades. Se os dados obrigatórios não puderem ser obtidos, o sistema informa o problema e preserva a lista.

## 10. Interface e backup do layout

No desktop, a interface utiliza três colunas: captura, reconhecimento e lista ativa. O título foi reduzido para aproveitar o espaço. Os controles principais e a exportação ficam disponíveis enquanto listas e resultados extensos usam rolagem interna.

As opções de captura e som ficam em uma seção recolhível, e as instruções estão no Guia de uso. Em telas estreitas, a página se reorganiza e permite rolagem. O rodapé apresenta Desenvolvido por Giovani Oliveira.

O README registra verificação de layout em 1280 × 720, 1366 × 768 e 1920 × 1080, com zoom padrão. Abrir opções adicionais em telas baixas pode exigir rolagem dentro do painel.

A interface anterior foi preservada em:

```text
backups/layout-anterior-20261014-89f8b2d8/
```

A pasta contém as instruções `COMO-RESTAURAR.md`. Restaurar esse layout não altera as listas salvas. Esse backup de interface não substitui o backup do banco de dados.

## 11. Organização do código

| Caminho | Responsabilidade |
| --- | --- |
| `app.py` | Configuração Flask, rotas, upload, pesquisa e integração dos serviços. |
| `scanner/recognition.py` | Preparação de imagens, OCR, normalização e ordenação de candidatos. |
| `scanner/identification.py` | Resolução da edição e metadados para exportação. |
| `scanner/catalog.py` | Consulta ao TCGdex e cache de cards e coleções. |
| `scanner/lists.py` | Persistência SQLite, validação de quantidades e geração dos formatos. |
| `templates/index.html` | Estrutura da página. |
| `static/app.js` | Interação, reconhecimento, listas, quantidades e exportação. |
| `static/webcam.js` | Seleção de dispositivos, captura, ciclo e som. |
| `static/style.css`, `static/layout.css`, `static/webcam.css` | Aparência e organização dos painéis. |
| `data/lists.sqlite3` | Banco das listas do usuário. |
| `tests/test_scanner.py` | Testes de reconhecimento, catálogo e API. |
| `tests/test_lists.py` | Testes de identificação, listas e exportações. |
| `scripts/check_live.py` | Integração com OCR e catálogo reais. |
| `scripts/check_browser.py` | Testes de interface com serviços e câmeras simulados. |
| `instalar.bat` | Criação do ambiente virtual e instalação das dependências. |
| `iniciar.bat` | Inicialização da aplicação. |
| `CardeScanner.md` | Resumo do Scanner. |
| `README.md` | Manual detalhado e limitações. |

O fluxo principal é: foto ou captura → preparação da imagem → OCR → comparação com catálogo → resolução da edição → inclusão na lista → conferência e exportação.

As rotas incluem `/api/scan`, `/api/search`, `/api/cards/<card_id>`, `/api/lists` e operações de itens e exportação por lista. `/api/access` informa o endereço disponível; `/qr.png` é habilitado somente no modo de rede.

## 12. Dados locais, internet e backup

O banco SQLite mantém listas, itens, quantidades, metadados e identificadores de inclusões. O catálogo e seus metadados possuem cache separado dentro de `data/` e podem ser reutilizados em caso de indisponibilidade. O catálogo é atualizado após sete dias, com fallback para cache.

A internet é utilizada para consultar o catálogo, detalhes e imagens de referência. Os modelos OCR também podem precisar de download no primeiro uso. Ter cache não garante que qualquer carta nunca consultada estará disponível sem internet.

Para proteger as listas:

1. Feche o aplicativo.
2. Copie `data/lists.sqlite3` para um local seguro.
3. Preserve esse arquivo antes de limpar qualquer conteúdo de `data/`.

As fotos enviadas ao OCR não são gravadas nem compartilhadas com o TCGdex. O navegador pode carregar imagens de referência do catálogo.

## 13. Instalação e utilização

1. Instale Python 3.11 a 3.13 de 64 bits.
2. Execute `instalar.bat` na primeira instalação.
3. Execute `iniciar.bat` e mantenha o terminal aberto.
4. Acesse `http://127.0.0.1:5000` no computador.
5. Crie ou selecione uma lista, escolha foto ou webcam e faça a leitura.
6. Confira as edições e quantidades e exporte no formato desejado.

Por padrão, o servidor aceita apenas conexões locais. Isso permite usar arquivo e webcam sem liberar conexões de entrada no firewall. O acesso à internet continua sujeito às políticas da rede.

Para outra porta, configure PORT antes de iniciar. Para encerrar, use Ctrl+C no terminal.

O modo opcional de rede é iniciado explicitamente com:

```powershell
.\.venv\Scripts\python.exe app.py --rede
```

Ele permite acesso pelo celular na mesma rede quando autorizado e disponibiliza QR code. Exige permissões da rede e firewall e não representa hospedagem pública. O fluxo de foto móvel utiliza um campo de arquivo com indicação de câmera; a disponibilidade depende do navegador. A captura contínua via API de vídeo por IP de rede em HTTP tem restrições de contexto seguro.

## 14. Testes disponíveis e alcance da validação

A suíte automatizada contém testes de nome e número, ambiguidade entre edições, conflitos de coleção, promocionais, energias básicas, quantidades, múltiplas listas, exclusão, persistência, reenvio de requisições e exportações.

Também existem verificações de API, tamanho e validade das imagens, preservação do texto quando o catálogo falha e uso de cache desatualizado em indisponibilidade.

O script de integração real utiliza catálogo, imagem de referência e OCR e verifica inclusão e exportação com uma lista temporária. O script de navegador utiliza OCR, catálogo e webcams simulados, sem acessar câmeras físicas ou alterar as listas reais. Ele cobre seleção e liberação de dispositivos, ciclos, som, repetição, parada, permissões, edição, exportação e layout.

Comandos disponíveis:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/check_live.py
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/check_browser.py
```

Nesta tarefa foi feita apenas a documentação: esses comandos não foram executados novamente. Este arquivo descreve os testes existentes e o alcance registrado no README, sem atribuir novos resultados ou uma taxa de precisão ao reconhecimento.

O uso de webcam física, celular vinculado e rede deve ser conferido no equipamento real. Não foi comprovada aqui a importação autenticada dentro do TCG Live ou de uma plataforma de torneios.

## 15. Limitações e continuidade

- Leitura de um card por vez, preferencialmente na vertical e com nome e rodapé legíveis.
- Reflexos, capas, desfoque, rotação e letras pequenas prejudicam o resultado.
- Sem reconhecimento visual da arte, correção de perspectiva ou processamento simultâneo de vários cards.
- Sem avaliação de autenticidade, conservação, acabamento holográfico ou preço.
- Cobertura de idioma e edições dependente do TCGdex.
- Sem validação competitiva do deck nem garantia de disponibilidade no TCG Live.
- Sem aplicativo Android/iOS nativo ou hospedagem HTTPS configurada.
- Câmeras e rede dependentes das permissões do sistema e do navegador.

Os próximos ajustes devem partir de exemplos reais de falhas de leitura e do teste nos dispositivos utilizados, preservando o banco das listas e o fluxo de exportação já implementado.

## 16. Documentação relacionada

- [README.md](README.md): manual completo, comandos e cuidados de uso.
- [CardeScanner.md](CardeScanner.md): resumo do projeto.
- [Restauração do layout anterior](backups/layout-anterior-20261014-89f8b2d8/COMO-RESTAURAR.md): retorno à interface preservada.

Projeto independente, sem afiliação à Pokémon. Cards e marcas pertencem aos respectivos titulares; dados e imagens de referência vêm do TCGdex.