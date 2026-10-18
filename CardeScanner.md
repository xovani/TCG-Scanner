# Card Scanner TCG — Resumo do projeto

**Desenvolvido por:** Giovani Oliveira  
**Resumo atualizado em:** 18/10/2026

## Objetivo

Aplicativo em Python para identificar cards Pokémon por foto ou webcam, montar várias listas de cards/decks e exportar os dados para TCG Live / Limitless ou para a procura de cartas da Liga Pokémon.

O servidor e o reconhecimento de texto são executados no computador. A interface abre no navegador e, por padrão, funciona em `http://127.0.0.1:5000`, sem exigir liberação de conexões de entrada no firewall.

## Funcionalidades principais

- **Leitura por arquivo:** seleção de foto, prévia, correção de orientação e opção de girar a imagem.
- **Leitura por webcam:** seleção entre as câmeras autorizadas pelo Windows e pelo navegador, incluindo o celular disponibilizado como câmera conectada pelo Windows.
- **Captura única ou contínua:** reconhecimento e inclusão automática na lista ativa, com bip após salvar. O intervalo entre leituras é de 2,5 segundos por padrão, ajustável para 2 ou 3 segundos, além do tempo de processamento.
- **Proteção contra repetição:** evita contar continuamente o mesmo card parado. Para outra cópia da mesma edição, é possível retirar o card até aparecer “Área livre” ou desativar a proteção.
- **Identificação por texto:** cruza nome, número do card e coleção, com suporte a português e inglês. Quando a edição permanece ambígua, apresenta candidatos para escolha manual.
- **Busca manual:** permite pesquisar nome, número e código da coleção.
- **Múltiplas listas persistentes:** criar, selecionar, renomear e apagar, com confirmação antes de excluir. Ao apagar a última lista, uma nova lista vazia é criada.
- **Edição de quantidades:** digitação direta, Enter ou saída do campo para salvar, Esc para cancelar e botões +, − e Remover. Aceita inteiros de 0 a 999; zero remove o card.
- **Rolagem estável:** editar quantidades mantém a posição da lista; novas inclusões são destacadas e trazidas para a área visível.
- **Exportação:** download de arquivo `.txt` ou cópia do texto para a área de transferência.

## Formatos de exportação

### TCG Live / Limitless

Opção única, com nomes em inglês, código da coleção, número do card e quantidade. Inclui seções por categoria e o total da lista.

```text
Pokémon: 1
4 Charizard ex OBF 125

Total Cards: 4
```

### Liga Pokémon — procura de cartas

Uma linha por edição, com quantidade, nome em inglês e numeração entre parênteses. Os componentes inteiramente numéricos têm pelo menos três dígitos; zeros existentes e prefixos são preservados. Coleções promocionais identificadas pelo catálogo usam infinito no denominador.

```text
4 Dragapult ex (130/167)
1 Mienfoo (052/086)
1 Jett (079/084)
1 Nome da carta (001/005)
4 Binacle (087/∞)
```

Listas antigas recebem os metadados necessários durante a exportação, sem alterar suas quantidades. Quando os dados exigidos não estão disponíveis, o aplicativo informa o problema em vez de inventar códigos ou totais.

## Funcionamento técnico

1. O navegador recebe a foto ou captura a área da moldura da webcam e envia a imagem ao servidor Python.
2. Pillow prepara a imagem; RapidOCR com ONNX Runtime extrai o texto usando CPU.
3. RapidFuzz compara os nomes com o catálogo TCGdex. A identificação cruza também número, código e total oficial da coleção.
4. Uma edição confirmada pode ser incluída automaticamente na lista ativa. Casos duvidosos aguardam escolha manual.
5. SQLite mantém listas, itens, quantidades e identificadores usados para evitar inclusões duplicadas por repetição de requisições.

**Tecnologias:** Python, Flask, Waitress, Pillow, NumPy, RapidOCR, ONNX Runtime, RapidFuzz, Requests, SQLite, HTML, CSS, JavaScript e QR code. Playwright é uma dependência opcional de desenvolvimento para os testes da interface.

## Estrutura do projeto

| Caminho | Responsabilidade |
| --- | --- |
| `app.py` | Servidor Flask, rotas HTTP e integração dos serviços. |
| `scanner/recognition.py` | Preparação das imagens, OCR e ordenação de candidatos. |
| `scanner/identification.py` | Confirmação da edição e preparação dos metadados de exportação. |
| `scanner/catalog.py` | Consultas e cache do catálogo TCGdex. |
| `scanner/lists.py` | Persistência SQLite, quantidades e formatos de exportação. |
| `templates/index.html` | Estrutura da interface. |
| `static/` | Estilos, controles das listas e captura por webcam. |
| `data/lists.sqlite3` | Banco das listas salvas. |
| `tests/` | Testes automatizados do reconhecimento, identificação, listas e API. |
| `scripts/check_live.py` | Integração real com catálogo, imagem de referência e OCR. |
| `scripts/check_browser.py` | Testes da interface com banco, catálogo, OCR e câmeras simulados. |
| `instalar.bat` / `iniciar.bat` | Instalação e inicialização no Windows. |
| `backups/` | Backup da interface anterior e instruções para restauração. |
| `README.md` | Documentação detalhada de uso e limitações. |

## Execução e uso

Requer Python de 64 bits, nas versões 3.11 a 3.13; o projeto foi desenvolvido e verificado com Python 3.13.

1. Na primeira instalação, execute `instalar.bat`.
2. Execute `iniciar.bat` e mantenha o terminal aberto.
3. Abra `http://127.0.0.1:5000` no computador.
4. Selecione ou crie uma lista, escolha arquivo ou webcam e inicie a leitura.
5. Confira os cards e as quantidades e escolha o formato de exportação.

Para o celular funcionar como webcam, ele precisa estar vinculado e habilitado como câmera conectada no Windows. Esse fluxo usa o navegador do computador. O modo opcional `app.py --rede` permite acesso pela rede local quando autorizado, mas continua dependendo das permissões da rede; webcam via navegador em IP de rede HTTP exige atenção ao requisito de contexto seguro.

## Interface

Layout compacto com três colunas no desktop: captura, reconhecimento e lista ativa. Os painéis mantêm os controles principais e a exportação visíveis, com rolagem interna para listas e resultados extensos. As opções de câmera e som ficam em uma seção recolhível, e as instruções no Guia de uso. O rodapé apresenta “Desenvolvido por Giovani Oliveira”. Em telas estreitas, a página se reorganiza e permite rolagem.

## Dados e cuidados de uso

As fotos são processadas em memória no computador; não são gravadas nem enviadas ao catálogo. A internet é usada para consultar e atualizar dados, carregar imagens de referência e, quando necessário, obter os modelos de OCR. O catálogo e seus metadados possuem cache local.

Para fazer backup das listas, feche o aplicativo e copie `data/lists.sqlite3`. Não exclua a pasta `data/` para limpar o cache sem preservar esse banco. O backup da interface anterior está em `backups/layout-anterior-20261014-89f8b2d8/`, com instruções em `COMO-RESTAURAR.md`.

## Validação e limites

A suíte automatizada é executada com:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Os scripts de integração e navegador estão em `scripts/`. Os testes de navegador usam dados e câmeras simulados, sem alterar as listas reais; a câmera física e o celular vinculado precisam ser conferidos no equipamento utilizado.

O reconhecimento depende de iluminação, foco, orientação e cobertura do catálogo. Deve-se apresentar um card por vez, com nome e rodapé legíveis. O aplicativo não avalia autenticidade, conservação, acabamento holográfico, preços ou legalidade de decks. Não realiza reconhecimento visual da arte nem correção de perspectiva. A exportação não garante que uma edição esteja disponível no jogo ou aceita em um torneio.

Projeto independente, sem afiliação à Pokémon. Cards e marcas pertencem aos respectivos titulares; os dados e imagens de referência são consultados no TCGdex.
