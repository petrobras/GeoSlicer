## Filtering Tools

Módulo _GeoSlicer_ que permite filtragem de imagens, conforme descrito abaixo:

1. Selecione uma ferramenta em _Filtering tool_.

2. Preencha as entradas necessárias e aplique.

### Gradient Anisotropic Diffusion

Módulo _GeoSlicer_ para aplicar filtro de difusão anisotrópica de gradiente a imagens, conforme descrito nos passos abaixo:

1. Selecione a imagem a ser filtrada em _Input image_.

2. Defina o parâmetro de condutância em _Conductance_. A condutância controla a sensibilidade do termo de condutância. Como regra geral, quanto menor o valor, mais fortemente o filtro preservará as bordas. Um alto valor causará difusão (suavização) das bordas. Note que o número de iterações controla o quanto haverá de suavização dentro de regiões delimitadas pelas bordas.

3. Defina o parâmetro de número de iterações em _Iterations_. Quanto mais iterações, maior suavização. Cada iteração leva a mesma quantidade de tempo. Se uma iteração leva 10 segundos, 10 iterações levam 100 segundos. Note que a condutância controla o quanto cada iteração suavizará as bordas.
   
4. Defina o parâmetro de passo temporal em _Time step_. O passo temporal depende da dimensionalidade da imagem. Para imagens tridimensionais, o valor padrão de de 0.0625 fornece uma solução estável.

5. Defina o nome de saída em _Output image name_.

6. Clique no botão _Apply_ e aguarde a finalização. O volume de saída filtrado estará localizado no mesmo diretório que o volume de entrada.

### Curvature Anisotropic Diffusion

Módulo _GeoSlicer_ para plicar filtro de difusão anisotrópica de curvatura em imagens, conforme descrito nos passos abaixo:

1. Selecione a imagem a ser filtrada em _Input image_.

2. Defina o parâmetro de condutância em _Conductance_. A condutância controla a sensibilidade do termo de condutância. Como regra geral, quanto menor o valor, mais fortemente o filtro preservará as bordas. Um alto valor causará difusão (suavização) das bordas. Note que o número de iterações controla o quanto haverá de suavização dentro de regiões delimitadas pelas bordas.
   
3. Defina o parâmetro de número de iterações em _Iterations_. Quanto mais iterações, maior suavização. Cada iteração leva a mesma quantidade de tempo. Se uma iteração leva 10 segundos, 10 iterações levam 100 segundos. Note que a condutância controla o quanto cada iteração suavizará as bordas.

4. Defina o parâmetro de passo temporal em _Time step_. O passo temporal depende da dimensionalidade da imagem. Para imagens tridimensionais, o valor padrão de de 0.0625 fornece uma solução estável.

5. Defina o nome de saída em _Output image name_.

6. Clique no botão _Apply_ e aguarde a finalização. O volume de saída filtrado estará localizado no mesmo diretório que o volume de entrada.

### Gaussian Blur Image Filter

Módulo _GeoSlicer para aplicar filtro de desfoque gaussiano a imagens, conforme descrito nos passos abaixo:

1. Selecione a imagem a ser filtrada em _Input image_.

2. Defina o parâmetro _Sigma_, o valor em unidades físicas (e.g. mm) do kernel gaussiano.

3. Defina o nome de saída em _Output image name_.

4. Clique no botão _Apply_ e aguarde a finalização. O volume de saída filtrado estará localizado no mesmo diretório que o volume de entrada.

### Median Image Filter

Módulo _GeoSlicer_ para aplicar filtro mediano a imagens, conforme descrito nos passos abaixo:

1. Selecione a imagem a ser filtrada em _Input image_.

2. Defina o parâmetro _Neighborhood size_, o tamanho da vizinhança em cada dimensão.

3. Defina o nome de saída em _Output image name_.

4. Clique no botão _Apply_ e aguarde a finalização. O volume de saída filtrado estará localizado no mesmo diretório que o volume de entrada.

### Shading Correction (temporariamente apenas para usuários Windows)

Módulo _GeoSlicer_ para aplicar correção de sombreamento a imagens, conforme descrito nos passos abaixo:

1. Selecione a imagem a ser corrigida em _Input image_.

2. Selecione a máscara de entrada em _Input mask LabelMap_ para ajustar as bordas do dado corrigido final.

3. Selecione a máscara de sombreamento em _Input shading mask LabelMap_, que proverá o intervalo de intensidades usado no cálculo de fundo.

4. Defina o o raio da bola do algoritmo rolling ball em _Ball Radius_.

5. Clique no botão _Apply_ e aguarde a finalização. O volume de saída filtrado estará localizado no mesmo diretório que o volume de entrada.
