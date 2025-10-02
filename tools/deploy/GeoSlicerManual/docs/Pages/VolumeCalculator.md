## Volume Calculator

O módulo **Volume Calculator** realiza operações matemáticas e lógicas utilizando os volumes carregados no projeto. É uma ferramenta flexível para combinar, modificar e analisar dados volumétricos através de fórmulas personalizadas.


#### Passo 1: Escrever a Fórmula

1.  Localize os volumes que deseja utilizar. Você pode usar o campo de filtro para encontrá-los mais facilmente.
2.  No campo **Formula**, digite a expressão matemática desejada.
3.  Para inserir um volume na fórmula, digite seu nome exatamente como aparece na árvore de dados, envolvendo-o com chaves `{}`. Alternativamente, dê um duplo-clique no nome do volume na árvore de dados para que ele seja inserido automaticamente no campo **Formula**.

Aqui estão alguns exemplos de fórmulas válidas:

*   **Operação aritmética simples:**
    ```
    {Volume1} + log({Volume2})
    ```
    Esta fórmula soma os valores do `Volume1` com o logaritmo dos valores do `Volume2`.

*   **Criação de máscara (limiarização):**
    ```
    {Volume1} < 10000
    ```
    Esta fórmula gera um novo volume binário (máscara). As regiões onde os valores do `Volume1` são menores que 10000 receberão o valor 1, e as demais receberão o valor 0.

*   **Aplicação de máscara:**
    ```
    ({Volume1} > 13000) * {Volume1}
    ```
    Esta fórmula primeiro cria uma máscara para os valores do `Volume1` maiores que 13000 e, em seguida, multiplica essa máscara pelo `Volume1` original. O resultado é um volume onde os valores abaixo do limiar são zerados.

[Lista completa de operadores e funções disponíveis](https://numexpr.readthedocs.io/en/latest/user_guide.html#supported-operators)

#### Passo 2 (Opcional): Usar Mnemônicos

Se os nomes dos volumes forem muito longos ou complexos, você pode usar mnemônicos (apelidos) para simplificar a escrita da fórmula.

1.  Expanda a seção **Mnemonics**.
2.  Clique no seletor **Mnemonic Table** para escolher uma tabela existente ou criar uma nova.
3.  Se criar uma nova tabela, ela aparecerá na área de visualização. Dê um duplo-clique nas células para editar e associar um **Volume name** a um **Mnemonic**.
4.  Use os botões **Add mnemonic** e **Remove selected mnemonics** para adicionar ou remover linhas da tabela.
5.  Com uma tabela de mnemônicos selecionada, ao dar um duplo-clique em um volume na árvore de dados, seu mnemônico será inserido na fórmula em vez de seu nome completo.

!!! note "Observação"
    As tabelas de mnemônicos são salvas na cena do _GeoSlicer_ dentro de uma pasta chamada `Volume Calculator Mnemonics`, permitindo que sejam reutilizadas em cálculos futuros.

#### Passo 3: Definir o Volume de Saída

1.  No campo **Output volume name**, digite o nome para o novo volume que será gerado com o resultado do cálculo.

#### Passo 4: Executar o Cálculo

1.  Clique no botão **Calculate**.
2.  A operação será executada, e uma barra de status informará o andamento.
3.  Ao final, o novo volume de saída será adicionado à cena, geralmente na mesma pasta ou diretório do primeiro volume utilizado na fórmula.

!!! warning "Alinhamento de Geometria (Reamostragem)"
    Se os volumes utilizados na fórmula possuírem geometrias diferentes (dimensões, espaçamento ou origem distintos), todos os volumes serão **automaticamente reamostrados** de forma temporária para corresponder à geometria do **primeiro volume** listado na fórmula. Embora essa reamostragem seja necessária para o cálculo, ela pode introduzir interpolação nos dados. Verifique se a ordem dos volumes na fórmula está de acordo com o resultado esperado.
