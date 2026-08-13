# Solução de Problemas & Perguntas Frequentes

Esta página reúne dúvidas comuns, mensagens de erro e soluções relatadas por usuários do GeoSlicer. Se o seu problema não estiver listado, siga as instruções de [reporte de bugs](#reportando-bugs) ao final da página.

---

## Instalação e Primeira Execução

### Onde devo instalar o GeoSlicer?

O GeoSlicer é uma aplicação autocontida que vem como `.exe` (Windows) ou `.sfx` (Linux).

!!! warning "NÃO instale em pastas sincronizadas"
    Evite instalar o GeoSlicer dentro de **Dropbox**, **OneDrive**, **Google Drive**, **iCloud** ou qualquer pasta corporativa sincronizada. O agente de sincronização briga com os arquivos da aplicação, causa corrupção intermitente e deixa a inicialização extremamente lenta.

!!! warning "NÃO instale em unidade de rede / mapeada"
    Unidades mapeadas (por exemplo, `Z:\...`) introduzem latência que deixa o startup e o carregamento de módulos muito lentos. Também podem gerar erros confusos na inicialização (por exemplo, `OSError: [WinError 112] Espaço insuficiente no disco` quando o GeoSlicer tenta acessar um caminho inválido).

!!! tip "Configuração recomendada"
    Instale o GeoSlicer em um **SSD local**, em um caminho curto sem espaços (por exemplo, `C:\GeoSlicer-x.y.z` ou `~/GeoSlicer-x.y.z`). Em VMs com limpeza periódica da pasta do usuário (ambientes tipo CIRRUS), reinstale em um local persistente.

### O GeoSlicer não inicia, módulos falham ao importar ou os arquivos parecem corrompidos

Se aparecer um traceback na inicialização mencionando módulos faltando ou caminhos inexistentes, o mais provável é instalação corrompida ou em um sistema de arquivos instável.

1. Apague a pasta do GeoSlicer por completo.
2. Baixe e descompacte novamente a partir da fonte oficial.
3. Extraia em um caminho de SSD local (não OneDrive/Dropbox/unidade de rede).
4. Desconecte unidades mapeadas que estejam offline ou sem espaço antes de iniciar — o GeoSlicer testa caminhos recentes no startup e pode travar em um caminho morto.

---

## Geral e Performance

### Por que o GeoSlicer demora tanto para abrir?

A inicialização é afetada por hardware, local de instalação e histórico de arquivos recentes. Verifique nesta ordem.

!!! warning "Plano de energia / Modo Econômico (muito comum)"
    Notebooks normalmente vêm com um plano de economia que limita a CPU bem abaixo do clock base (por exemplo, 1,6 GHz no lugar de 2,1 GHz). Isso impacta fortemente o tempo de carga do GeoSlicer. Mude o plano para **Alto Desempenho / Performance / Máximo Desempenho** e conecte a máquina na tomada.

**Outras coisas a tentar:**

1. **Limpe a lista de arquivos recentes.** O GeoSlicer herda um comportamento do 3D Slicer no qual cada entrada de *recentes* é testada no startup. Se alguma dessas entradas estiver em um compartilhamento de rede lento ou offline, o startup pode passar de ~20 s para vários minutos. Abra *File → Recent → Clear History* e reinicie.
2. **Execute de um SSD local** — não OneDrive/Dropbox, não unidade de rede mapeada.
3. **Avançado — edite `slicerrc.py`:** No diretório raiz do GeoSlicer, abra `slicerrc.py` e comente módulos opcionais dentro da função `loadFoundations`. Salve antes de reiniciar. Peça à equipe de desenvolvimento um snippet recomendado.

### O carregamento do projeto está travado (por exemplo, em 57%). O que faço?

Quase sempre é latência de rede ao abrir um projeto grande (90 GB+) em compartilhamento padrão.

- **Use armazenamento rápido.** Mova datasets pesados para um sistema de arquivos de alta performance (por exemplo, Lustre em um cluster corporativo). É drasticamente mais rápido que uma rede de pesquisa comum.
- **Reduza o projeto.** Remova imagens não utilizadas, volumes intermediários e segmentações antigas antes de salvar.
- **Tenha paciência na primeira abertura.** Mesmo um projeto saudável de 90 GB na rede pode levar ~1 hora para carregar. Confira os logs para confirmar que o carregamento ainda está progredindo.
- **Reconecte à sua sessão.** No GeoSlicer Cloud, é possível reconectar à mesma sessão em vez de começar do zero.

### Como limpar jobs remotos "travados" / "zumbis"?

Se uma simulação remota travou após queda de conexão, ou se aparece `paramiko.ssh_exception.SSHException: SSH session not active` no console, o manifesto local de jobs está dessincronizado com o cluster.

!!! warning
    Antes de apagar qualquer coisa, confirme que nenhuma simulação está realmente rodando no cluster (`squeue -u <seu_usuario>` no nó head). Caso contrário, você vai perder o rastreio de resultados em andamento.

1. Feche o GeoSlicer.
2. Navegue até `%AppData%\Roaming\lib\remote\` no Windows ou o caminho equivalente no Linux.
3. Apague manualmente o `jobs.json`.
4. Reabra o GeoSlicer e tente recuperar os resultados esperados.

Você também pode tentar o snippet de recuperação no Console Python antes de apagar o arquivo:

```python
def restart_jobs():
    from lib.remote.jobs import JobManager
    for uid in JobManager.jobs:
        JobManager.schedule(uid, "PROGRESS")
    print(JobManager.agenda.qsize())

restart_jobs()
```

### A memória não é liberada

O GeoSlicer mantém histórico de undo/redo por nó, que cresce rápido em volumes grandes.

- Apague nós temporários que você não precisa mais no módulo Data.
- Feche o projeto (*File → Close Scene*) antes de carregar um segundo dataset grande.
- Use crops / sub-volumes ao iterar em parâmetros.

---

## Importação e Exportação de Dados

### Erro "Wrong array size" ao carregar um `.raw`

Acontece quando as dimensões X/Y/Z ou o tipo de dado (Int16, Float, UInt8, …) não correspondem ao conteúdo sem cabeçalho do arquivo — por exemplo, depois de cortar um volume e esquecer que o tipo virou `float32`.

!!! tip
    Habilite **Real-time update** no loader RAW, coloque **Z = 1** e itere pelos valores de X/Y e tipo de dado até o preview da fatia ficar correto. Só então ajuste o valor final de Z.

Mapas de porosidade normalmente são `float`, mesmo quando o volume binário original era inteiro.

### `AttributeError: 'NoneType' object has no attribute 'GetDimensions'`

É consequência do erro de tamanho acima: como o loader RAW não produziu uma imagem válida, o pós-processamento (auto-crop) quebra. Ajuste as dimensões e o tipo de dado primeiro; o preview voltará a funcionar.

### Por que o botão "Export" está cinza?

Bug conhecido de atualização da interface.

- **Workaround:** Selecione novamente o diretório de saída ou o nó do volume. Alternar a pasta de destino costuma "acordar" o botão.
- Confirme que a unidade de destino não é uma rede desconectada.

### Erros de encoding ao importar CSV (PcHg, SIRR, …)

O GeoSlicer espera CSVs em **UTF-8** com convenção consistente de separador e decimal.

- **Corrija o encoding:** Abra o arquivo em um editor como **Notepad++**, escolha *Encoding → Convert to UTF-8* e salve.
- **Separador:** O Excel costuma salvar CSV com `;` como separador e `,` como decimal. O loader do GeoSlicer espera valores **separados por vírgula** com formato numérico consistente. Re-salve com `,` como separador ou troque os delimitadores em um editor de texto.
- **Limpe o lixo:** Remova delimitadores no final, cabeçalhos mesclados e quaisquer caracteres não imprimíveis deixados pelo Excel.

### Por que usar o formato netCDF (`.nc`)?

`.nc` é o contêiner recomendado para mapas de porosidade e datasets multi-escala (alta e baixa resolução registradas).

- Preserva o registro espacial e os metadados, então crops consistentes e simulações em alta resolução em sessões diferentes funcionam direto.
- Arquivos `.nc` de tomografia médica também são suportados pelo Loader padrão (um loader médico dedicado está no roadmap).

### Nomes de amostras enviadas ao cluster: evite espaços e hífens

Ao submeter jobs pelo Microtom / Remote, nomes contendo **espaços** ou **`-` no início** são interpretados como flags pelo shell e o job falha silenciosamente. Use apenas letras ASCII, dígitos, underline e ponto.

---

## Visualização

### A imagem sumiu (ficou preta/invisível) depois de aplicar um filtro

Alguns filtros (por exemplo, **Gradient Anisotropic Diffusion**, **Median**) ocasionalmente fazem a lookup table "Gray" desaparecer no resultado filtrado. O histograma continua correto — o problema é apenas o colormap.

**Correção:** Abra o módulo **Volumes** e troque a **Lookup Table** de "Gray" para **"Viridis"** (ou qualquer outra). Em geral, voltar para "Gray" depois funciona.

### Como remover as linhas de grade / caixas / interseções de fatia na vista 3D?

Essas linhas são interseções de fatia introduzidas na base nova do 3D Slicer.

- **Mais fácil:** Na barra de ferramentas da vista 3D, clique no botão para desativar **Slice Intersections**. Há um pequeno dropdown ao lado para manter a fatia visível mas esconder a borda.
- **Alternativa:** Alterne o ícone do olho dos nós de fatia no módulo Data — note que isso também esconde o plano da fatia no 3D.

### O mapa de cores 3D não muda quando ajusto os sliders 2D

No 3D Slicer (e no GeoSlicer), o ajuste de janela das fatias 2D e o volume rendering 3D são tratados separadamente — os sliders abaixo do visualizador 2D **não** recolorem o volume 3D.

**Solução:** Pressione <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>F</kbd> e procure por **Volume Rendering**. Ajuste as funções de transferência (opacidade/cor) do modelo 3D ali.

### Melhorar contraste rapidamente para destacar uma fase

Segure <kbd>Ctrl</kbd> e arraste o mouse sobre uma região de interesse em uma fatia 2D. O GeoSlicer ajusta automaticamente window/level para aquela região, o que destaca fases minerais e facilita a segmentação manual.

### Renderizar uma segmentação grande em 3D sem travar o GeoSlicer

O "Show 3D" em uma segmentação complexa tenta mesh em todos os segmentos, o que pode estourar a memória em volumes grandes.

**Workaround:** Na árvore de Data, clique com o botão direito na segmentação → **Export visible segments to binary labelmap** → selecione o labelmap criado → marque **Render in 3D**. Isso renderiza o volume diretamente, pulando a geração de superfície, e é muito mais rápido.

---

## Segmentação e Registro

### Fluxo correto de Registro / Transformação manual

Ao alinhar amostras "Seca" e "Saturada":

!!! warning "A ordem importa"
    Sempre faça **Rotação primeiro** e depois **Translação**.

- Trocar o eixo ou usar as setas após uma transformação parcial pode redefinir os valores para a origem se as etapas forem aplicadas fora de ordem. Siga a ordem com rigor e clique em *Apply* antes de alternar entre rotação e translação.
- Para o ajuste fino, faça um posicionamento manual grosseiro e deixe o **registro automático** terminar — o automático sozinho raramente converge em rochas heterogêneas.
- O registro automático é instável entre resoluções diferentes (alta vs. baixa do mesmo plug). Use metadados coordenados (por exemplo, bounding box de `.am` / `.nc`).

### Posso usar o AI Segmenter para tipos de rocha / texturas?

Sim. Os segmentadores **Bayesiano** e **Random Forest** funcionam bem para particionar tipos de rocha, fácies ou regiões de porosidade variável. Veja a seção [AI Segmenter](/Volumes/Segmentation/Segmentation.md#ai-segmenter) do manual.

!!! warning "Memória"
    Em volumes grandes (~1000³ ou mais), só o passo de features pode exigir dezenas de GB. Uma alocação de 80+ TiB derruba a aplicação. Use crops para treinamento.

**Treine em um crop, infira no volume completo:** Coloque a imagem cortada em *Input Image*, anote, depois selecione a imagem completa em *Inference Image* (perto de *Apply to Full Image*) e clique em apply.

### Parâmetros do Variogram Analysis estão cinza

É necessário definir um **SOI (Segment Of Interest)** para liberar os parâmetros opcionais. A restrição existe para evitar variograma sobre voxels de background, o que pode arruinar o cálculo.

Referência rápida dos parâmetros:

| Parâmetro | Significado |
|-----------|-------------|
| Sampling rate | Fração de voxels usada; menor = mais rápido, menos preciso. |
| Maximum number of samples | Limite máximo de pontos; trade-off velocidade × precisão. |
| Number of lags | Análogo a bins do histograma no eixo X (distância). |
| Directional tolerance | Janela angular ao redor de X/Y/Z. Para micro-CT denso, use < 60°. |
| Maximum distance | Limite manual (mm) do alcance do variograma. |

### Valores de "Sphere diameter" do Inspector parecem errados (gigantes)

Quase sempre é erro de **voxel size / spacing** na importação. Mesmo que a caixa da amostra pareça correta na vista 3D, um pixel size errado escala silenciosamente todas as métricas de comprimento.

- Confira o spacing do volume no módulo Volumes.
- Confirme se a importação usou as unidades corretas (µm vs. mm).
- Reimporte se necessário e rode o Inspector de novo.

Definições das principais métricas do Inspector:

- `voxelCount` — número de voxels no poro.
- `volume` — `voxelCount × volume do voxel`.
- `sphere_diameter_from_volume` — diâmetro da esfera com o mesmo volume do poro.
- `ellipsoid_volume` — volume do menor elipsoide com o mesmo momento de inércia do poro.
- `max_feret` — diâmetro de Feret máximo.
- `pore_size_class` — classe categórica (megaporo / macroporo / mesoporo / microporo). Limites seguem Choquette & Pray (1970), AAPG Bulletin 54, pp. 207–250.

### Os valores de Coverage no relatório do Porosity Map não batem com as proporções dos segmentos

Particularidade conhecida: as linhas de *Coverage* do relatório do mapa de porosidade são normalizadas pelo **volume total**, não pelo SOI, enquanto a tabela de proporções dos segmentos é normalizada dentro do SOI. Os dois só coincidem quando o SOI cobre o volume inteiro. Correção no roadmap.

---

## Simulações (PNM, Kabs, MICP, Krel)

### Os resultados de Kabs (Permeabilidade) saem 10× (ou mais) errados

Quase sempre **inconsistência de unidades**:

- **Queda de pressão** precisa estar na unidade esperada pelo simulador (normalmente **Pascal**). Em algumas versões 2.8.x um bug de escala fazia o resultado depender linearmente da pressão de entrada — corrigido em **2.8.2**. Atualize se você estiver em uma versão anterior.
- **Unidades de comprimento** nos modelos de sub-resolução devem ser **micrômetros**, não milímetros. O default de 100 µm é grosseiro demais para imagens de alta resolução (por exemplo, 4 µm); ajuste para próximo do seu pixel size. Versões mais novas leem o pixel size do volume automaticamente.
- **Washburn / pressão capilar (Hg):** use ângulo de contato ≈ 140°, tensão interfacial ≈ 470 mN/m e mantenha consistência de escala (µm vs. mm) ao converter psi ↔ Pa.

### A simulação PNM terminou, mas os resultados estão em branco / zerados

Em ordem de probabilidade:

1. **Escala do mapa de porosidade (somente 2.8.0).** A 2.8.0 só aceitava microporosidade no intervalo **[0..100]**. Se seu mapa estiver em [0..1], multiplique por 100 (Volume Calculator) ou faça o cast do array:
    ```python
    import numpy as np
    node = slicer.mrmlScene.GetFirstNodeByName('Porosity_map_100')
    arr  = slicer.util.arrayFromVolume(node).astype(np.uint8)
    slicer.util.addVolumeFromArray(arr, name='Porosity_map_int')
    ```
    Em seguida rode a extração no `Porosity_map_int`. A **2.8.1+** detecta a escala automaticamente.
2. **Todos os poros marcados como sub-resolvidos / não-resolvidos.** Afetava a 2.8.0; corrigido na **2.8.1**. Atualize.
3. **Sem percolação.** Sem caminho conectado do inlet ao outlet, Kabs = 0 por construção.
4. **Problema no cluster.** A imagem do cluster pode ter sido atualizada no meio da execução. Reenvie o job. "Completed com resultados vazios" é a assinatura típica.
5. **Versão do software.** Confirme que está na última estável (**2.8.2+** para a correção da pressão, **2.8.7+** para correções adicionais de MICP e remote).

### Minha PNM multi-escala ficou "pessimista" (microporosidade domina)

Duas causas comuns:

- **Parâmetros do modelo de sub-resolução em unidade errada** — micrômetros, não milímetros.
- **Gaussiana Truncada vs. distribuição ajustada ao MICP:** se o MICP devolve uma distribuição muito fina, o modelo de subescala superpondera poros pequenos. Use a **Gaussiana Truncada Logarítmica** (2.8.7+) ou relaxe o limite inferior para que a faixa de microporosidade se sobreponha à da rede resolvida.

### O ciclo 3 do Krel (segunda drenagem) não respeita o Swi

Bug conhecido — em algumas builds 2.8.x o segundo ciclo de drenagem puxava a saturação de água para perto de 0, ignorando o Swi alvo. Corrigido; confirme que está em **2.8.2+** e rode de novo.

### Pontos por poro / garganta no VTK

- **Poro:** 50 pontos por esfera — `NumberOfPoints / 50` = número de poros.
- **Garganta:** 12 pontos por garganta — `NumberOfPoints / 12` = número de gargantas.
- O tamanho das esferas no modelo ainda não pode ser editado de forma interativa, mas a partir da **2.8.0** elas são redimensionadas automaticamente em função do raio do poro.

### Automatizando simulações para múltiplos crops

A UI foi feita para uso manual, mas é possível dirigir via **Console Python**.

Para **cubos justapostos / empilhados estilo REV**, modifique o loop de cropping em `PoreNetworkKabsREVCLI.py` (em torno da linha 151 do módulo upstream — veja o [repositório público do GeoSlicer no GitHub](https://github.com/petrobras/GeoSlicer)). Também é possível editar o arquivo direto na sua instalação:

```
GeoSlicer-x.y.z/lib/GeoSlicer-5.8/qt-scripted-modules/PoreNetworkKabsREV/PoreNetworkKabsREVCLI/PoreNetworkKabsREVCLI.py
```

Para Kabs em lote sobre sub-volumes arbitrários, peça um template de script à equipe de desenvolvimento. O **Pore Network KABS REV** nas versões mais recentes tem execução remota — use-o para jobs multi-escala que demorariam horas localmente.

### Onde salvo / recarrego os parâmetros da simulação?

O botão *Save parameters* foi removido porque os parâmetros agora são **salvos automaticamente** junto com o nó da simulação. Para recuperar uma configuração antiga, clique em **Load parameters** e selecione o nó `simulation_parameters` dentro da pasta da simulação concluída anterior; o formulário será repopulado.

---

## GeoSlicer Cloud / Remote

### Sessões travam em "Launching session…"

Em geral é problema transitório no filesystem do cluster (contenção de stripe no Lustre, `/server` não montando em algum nó).

- Tente novamente após alguns minutos.
- Verifique com o admin do cluster se o filesystem compartilhado está acessível pelo nó que hospeda o launcher.
- O launcher v1.1+ tem fallback para essas indisponibilidades.

### Jobs remotos terminam como "Completed" mas não retornam resultados

Causas mais comuns:

- Uma atualização da imagem do GeoSlicer no cluster ocorreu durante o job (veja o timestamp da submissão).
- Nomes de job com **espaços** ou **`-` no início** são engolidos pelo shell.
- O caminho do PNM remoto precisa de `partition=gpu` apenas, não `partition=gpu,cdi_server_gpu` — configurações antigas podem deixar o job preso em PENDING para sempre.

Em caso de suspeita de falha silenciosa, deixe o job na lista do GeoSlicer (não cancele, não delete) e contate a equipe de desenvolvimento para inspecionar os artefatos do cluster.

### Rodar várias instâncias do GeoSlicer em uma sessão Cloud

Hoje o Cloud abre um GeoSlicer por chave por sessão. Enquanto um processamento lento roda em um projeto, é possível disparar um job remoto de PNM/Kabs, fechar o projeto e abrir outro — o job continua rodando no cluster. Suporte a múltiplas instâncias (vários GeoSlicers na mesma sessão Slurm) está em desenvolvimento.

### Animações criadas com "Create animation node" não aparecem no Remote

Problema conhecido — a exportação de animação ainda não é propagada de volta do Cloud. Rode a animação localmente por enquanto.

### Como rodar o GeoSlicer Cloud em tela cheia

O Cloud é uma web app. No Edge / Chrome, pressione <kbd>F11</kbd> ou abra o menu do navegador (⋮) e escolha *Tela cheia*. Em alguns navegadores o atalho é <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>F</kbd>. Passe o mouse no topo da tela para a barra do navegador reaparecer ou segure <kbd>Esc</kbd> para sair.

---

## Citação e Referências

### Como cito o GeoSlicer em um artigo?

Cite o repositório do projeto diretamente:

> Passos de Figueiredo, L., et al. (2025). *GeoSlicer — Integrated Open-Source Digital Rocks Platform* [Software]. https://github.com/petrobras/GeoSlicer

O GitHub também gera automaticamente citações em **Cite this repository** no lado direito da página do repositório, nos formatos BibTeX, APA e outros.

### Citando as classes de tamanho de poro do Inspector

Os limites das classes seguem Choquette, P. W., & Pray, L. C. (1970), *Geologic Nomenclature and Classification of Porosity in Sedimentary Carbonates*, AAPG Bulletin 54, 207–250.
DOI: <https://doi.org/10.1306/5D25C98B-16C1-11D7-8645000102C1865D>

### Documentação para filtros não descritos no manual

O módulo **Simple Filters** encapsula filtros do SimpleITK e herda a documentação deles:

- [Referência do Simple Filters no 3D Slicer](https://slicer.readthedocs.io/en/latest/user_guide/modules/simplefilters.html)

---

## Reportando Bugs

Se você encontrar um erro que não consegue resolver:

1. Clique no **ícone do inseto** (Bug Report) na barra lateral direita.
2. Escreva uma breve descrição do que estava fazendo e do comportamento esperado.
3. O GeoSlicer gera um `.zip` com os logs recentes — envie para a equipe de suporte da LTrace junto com o projeto (`.mrml` + pasta de dados) se for possível compartilhar.
4. Sempre que possível, prepare um **caso mínimo de reprodução**: um crop pequeno dos dados que ainda dispara o bug. A maioria dos problemas é corrigida em um ou dois ciclos de release quando há um caso reproduzível.

Para discussões mais longas e busca em problemas já resolvidos, use o fórum público: <https://discourse.ltrace.com.br/>.
