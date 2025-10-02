## Azimuth Shift

O módulo **Correção de Azimute** aplica uma rotação em perfis de imagem acústica (como UBI) para corrigir desalinhamentos rotacionais causados pelo movimento da ferramenta no poço.

Perfis de imagem acústica são desenrolados em 2D, onde uma dimensão é a profundidade e a outra é o azimute (0 a 360 graus). Durante a aquisição, a ferramenta de perfilagem pode girar, o que distorce a aparência de estruturas geológicas.

Este módulo utiliza uma tabela de azimute para rotacionar cada linha da imagem de volta à sua orientação correta, garantindo que as feições geológicas sejam exibidas de forma consistente e interpretável.

### Como Usar

1.  **Image node:** Selecione o perfil de imagem que você deseja corrigir.
2.  **Azimuth Table:** Escolha a tabela que contém os dados de azimute. Esta tabela deve conter uma coluna de profundidade e uma coluna com os valores de desvio de azimute em graus.
3.  **Table Column:** Selecione a coluna específica na tabela que contém os valores de azimute a serem usados para a correção.
4.  **Invert Direction (Opcional):** Marque esta caixa se desejar que a rotação seja aplicada no sentido anti-horário. Por padrão, a rotação é no sentido horário.
5.  **Output prefix:** Defina o nome para a imagem corrigida que será gerada.
6.  **Clique em Apply:** Pressione o botão para iniciar o processo de correção.

### Saída

O resultado é uma nova imagem no projeto com a correção azimutal aplicada.