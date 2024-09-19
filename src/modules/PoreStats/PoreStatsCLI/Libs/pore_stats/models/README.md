# [Segmentação de Oóides](ooids/)

Modelos e configurações [StarDist](https://github.com/stardist/stardist) para detecção de oóides [grandes](ooids/big/) e [pequenos](ooids/small/), treinados e testados utilizando [estes notebooks](../notebooks/ooids/). Os experimentos foram realizados sobre um [*dataset*](https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/_XT9exwjkIDntKSrJI5ZFQCm_29LyzGI8v_Axs-XS4F-mvLorSql9BuP8Y6GlFSm/n/grrjnyzvhu1t/b/General_ltrace_files/o/ThinSection/atc-tvd/Datasets/Ooids_dataset.zip) de 74 recortes de tamanhos variados divididos em 37 de treino e 37 de validação, sendo que cada recorte de treino foi tirado de uma imagem diferente e cada recorte de validação corresponda a outras áreas das mesmas imagens. 33 dos 37 recortes de cada conjunto têm oóides rotulados. Os modelos finais foram treinados com todas as 74 imagens.

O modelo para oóides pequenos foi treinado sobre um modelo pré-treinado (`2D_versatile_he`) de tamanho de grade (*grid size*) de 2 (ou seja, tenta-se prever centros de oóides a cada 2 pixeis de distância), enquanto o para oóides grandes foi treinado do zero com *grid size* 8, aumentando a distância entre as predições e permitindo que oóides maiores sejam preditos como objetos únicos e não divididos em vários menores. Na etapa de predição, a ideia é que o modelo para maiores seja executado primeiro e sua contraparte seja usava para detectar os menores apenas na área onde não foram detectados os grandes.

# [Limpeza de poros](pore_residues/)

Série de modelos *K-Means* treinados utilizando [este *notebook*](../notebooks/kmeans4bubbles.ipynb). Os modelos podem isolar diferentes regiões da imagem onde a presença de bolhas e resíduos na resina de poro é provável. Cada um deles foi treinado sobre a versão tingida de todas as imagens dos lotes RJS-702, RJS-661, TMT-1D e TVD-11D, utilizando apenas a variante PP ou PX. As dimensões das imagens foram reduzidas em 10x para um treinamento mais eficiente.

* `blue_channel.pkl`: modelo treinado sobre o canal azul das imagens PP para dividí-lo em 4 *clusters*. O histograma do canal é equalizado para realçar as diferentes regiões. O *cluster* de maior centróide isola bem as regiões da imagem com canal azul mais forte, como a resina de poro e as bolhas brancas;
* `hue_channel.pkl` (atualmente não-usado): modelo treinado sobre o canal matiz (*hue*) das imagens PP para dividí-lo em 2 *clusters*. O histograma do canal é equalizado para realçar as diferentes regiões. O *cluster* de maior centróide isola bem as regiões da imagem com matiz mais forte, como a resina de poro e as bolhas negras e resíduos;
* `px_hsv.pkl`: modelo treinado para dividir o espaço HSV da imagem PX em 4 *clusters*. A imagem passa por um borramento razoável para unificar regiões que seriam separadas por pequenos ruídos. Um dos *clusters* isola bem a região com provável presença de poros (região "extinta", onde a intensidade da luz é quase nula) e, consequentemente, abrange as bolhas e resíduos, também extintos.

# [Remoção de poros espúrios](spurious_removal/)

Série de modelos *Random Forest* treinados utilizando [este *notebook*](../notebooks/spurious_pores_analysis.ipynb). Cada modelo foi treinado sobre detecções de poros realizadas com um dos 3 diferentes modelos de segmentação de poros disponíveis para uso. O [*dataset*](https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/mW4syHrY2DIHUR4Nc5IL7K_fS1GPsA1IC4MfEaMSr2v9N6QFdPdzuzuicy3_moA9/n/grrjnyzvhu1t/b/General_ltrace_files/o/ThinSection/atc-tvd/Datasets/Spurious_pores_dataset.zip) consiste em recortes de 6 imagens do lote RJS-702 em que os poros válidos e espúrios estão rotulados. Os treinamentos experimentais foram validados por validação cruzada utilizando 4 imagens, e as outras 2 foram utilizadas para teste. Os modelos finais, porém, são treinados sobre todas as 6 imagens. Para treinamento, uma região 10x10 ao redor do centróide de cada poro detectado foi utilizada. Para casos em que o centróide reside fora do segmento de poro, a coordenada mediana do poro logo à esquerda é consultada. Caso não exista, consulta-se o lado direito e assim sucessivamente para cima e para baixo.