# Links

## Links de página

Se a **navegação for importante**, crie um link para o caminho completo:

```
[Saturação](/Volumes/Microporosity/Microporosity.md)
```

O caminho absoluto é convertido em um caminho relativo durante a compilação.

Após clicar, o seguinte caminho será aberto na barra de navegação: *Volumes > Microporosity*

Se a **navegação não for importante**, você pode criar um link direto:

```
[Saturação](Microporosity.md)
```

Isso é equivalente a `./Microporosity.md` e pressupõe que todas as páginas estão no mesmo diretório.

## Imagens

```
![alt text](/assets/images/foo.png)
```

O caminho absoluto também é convertido em um caminho relativo durante a compilação.

## Vídeos

```
{{ video("video_name.webm", caption="Legenda opcional") }}
```

Os vídeos são automaticamente obtidos de `/assets/videos/`.

## Âncora

Para compatibilidade com vários idiomas, use a tag `<a>` no texto do cabeçalho desejado, incluindo a definição `id` em _english_.

Essa abordagem garante que um link como `[algum texto](page.md#title-simulation)` navegue para a seção correta, independentemente de o usuário estar visualizando a página em inglês ou português. Isso também evita que o `mkdocs` relate links quebrados durante o processo de compilação.

```
Cabeçalho na página em português:
<a id="title-simulation">Simulação de Título</a>

Cabeçalho na página em inglês:
<a id="title-simulation">Title Simulation</a>
```