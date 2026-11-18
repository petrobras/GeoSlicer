from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.node_attributes import NodeEnvironment
from unittest.mock import patch
from .util_segmenter import (
    MICROCT_BORDER_PROJECT_FILE,
    PORE_CLEANING_PROJECT_FILE,
    TEXTURA_SINTETICO_2D_PROJECT_FILE,
    TEXTURA_SINTETICO_3D_PROJECT_FILE,
    QEMSCAN_PROJECT_FILE,
    RANDOM_FOREST_METHOD_LABEL,
    BAYESIAN_INFERENCE_METHOD_LABEL,
    PRE_TRAINED_MODEL_LABEL,
    THIN_SECTION_INSTANCE_SEGMENTER_PROJECT_FILE,
    buttons_visibility_test_on_pre_trained,
    cleaning_visibility_test_on_pre_trained,
    instance_segmenter_recommended_settings_test_process,
    populate_widgets,
    common_successful_test_process,
)


class SegmenterTest(LTracePluginTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = dict()
        populate_widgets(self)

    def tear_down(self):
        del self._widgets

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_random_forest_2d_raw(
        self,
        update_template: bool = False,
    ):
        # Random Forest method configuration:
        # Segmentation: Segmentation
        # Image: Texture_ToyModel_10000nm
        # Features: raw
        common_successful_test_process(
            cls=self,
            method=RANDOM_FOREST_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="Texture_ToyModel_10000nm",
            features={"raw": True},
            template_prefix="Texture_ToyModel_10000nm_raw",
            random_seed=5423,
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_random_forest_2d_raw_keep_features(
        self,
        update_template: bool = False,
    ):
        # Random Forest method configuration:
        # Segmentation: Segmentation
        # Image: Texture_ToyModel_10000nm
        # Features: raw
        common_successful_test_process(
            cls=self,
            method=RANDOM_FOREST_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="Texture_ToyModel_10000nm",
            features={"raw": True},
            template_prefix="Texture_ToyModel_10000nm_raw",
            random_seed=5423,
            keep_features=True,
            features_names=["Texture_ToyModel_10000nm_raw_Filtered_Img0_raw"],
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_random_forest_2d_quantized(
        self,
        update_template: bool = False,
    ):
        # Random Forest method configuration:
        # Segmentation: Segmentation
        # Image: Texture_ToyModel_10000nm
        # Features: quantized
        common_successful_test_process(
            cls=self,
            method=RANDOM_FOREST_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="Texture_ToyModel_10000nm",
            features={"quantized": True},
            template_prefix="Texture_ToyModel_10000nm_quantized",
            random_seed=5423,
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_random_forest_2d_petrobras(
        self,
        update_template: bool = False,
    ):
        # Random Forest method configuration:
        # Segmentation: Segmentation
        # Image: Texture_ToyModel_10000nm
        # Features: petrobras
        common_successful_test_process(
            cls=self,
            method=RANDOM_FOREST_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="Texture_ToyModel_10000nm",
            features={"petrobras": True},
            template_prefix="Texture_ToyModel_10000nm_petrobras",
            random_seed=5423,
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_random_forest_2d_gaussian(
        self,
        update_template: bool = False,
    ):
        # Random Forest method configuration:
        # Segmentation: Segmentation
        # Image: Texture_ToyModel_10000nm
        # Features: gaussian
        common_successful_test_process(
            cls=self,
            method=RANDOM_FOREST_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="Texture_ToyModel_10000nm",
            features={"gaussian": {"sigma": [0.1]}},
            template_prefix="Texture_ToyModel_10000nm_gaussian",
            random_seed=5423,
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_random_forest_2d_gaussian_keep_features(
        self,
        update_template: bool = False,
    ):
        # Random Forest method configuration:
        # Segmentation: Segmentation
        # Image: Texture_ToyModel_10000nm
        # Features: gaussian
        common_successful_test_process(
            cls=self,
            method=RANDOM_FOREST_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="Texture_ToyModel_10000nm",
            features={"gaussian": {"sigma": [0.1]}},
            template_prefix="Texture_ToyModel_10000nm_gaussian",
            random_seed=5423,
            keep_features=True,
            features_names=["Texture_ToyModel_10000nm_gaussian_Filtered_Img0_gaussian0"],
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_random_forest_2d_winvar(
        self,
        update_template: bool = False,
    ):
        # Random Forest method configuration:
        # Segmentation: Segmentation
        # Image: Texture_ToyModel_10000nm
        # Features: winvar
        common_successful_test_process(
            cls=self,
            method=RANDOM_FOREST_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="Texture_ToyModel_10000nm",
            features={"winvar": {"sigma": [0.3]}},
            template_prefix="Texture_ToyModel_10000nm_winvar0.3",
            random_seed=5423,
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def DISABLED_test_random_forest_2d_winvar_keep_features(
        self,
        update_template: bool = False,
    ):
        # Random Forest method configuration:
        # Segmentation: Segmentation
        # Image: Texture_ToyModel_10000nm
        # Features: winvar
        # Disabled due accuracy instability in CI/CD VM (using Mesa3D driver)
        # TODO (PL-2129): Review Segmenter test related to winvar feature
        common_successful_test_process(
            cls=self,
            method=RANDOM_FOREST_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="Texture_ToyModel_10000nm",
            features={"winvar": {"sigma": [0.1]}},
            template_prefix="Texture_ToyModel_10000nm_winvar",
            random_seed=5423,
            keep_features=True,
            features_names=["Texture_ToyModel_10000nm_winvar_Filtered_Img0_winvar0"],
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_random_forest_2d_gabor(
        self,
        update_template: bool = False,
    ):
        # Random Forest method configuration:
        # Segmentation: Segmentation
        # Image: Texture_ToyModel_10000nm
        # Features: gabor
        common_successful_test_process(
            cls=self,
            method=RANDOM_FOREST_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="Texture_ToyModel_10000nm",
            features={"gabor": {"sigma": [0.1], "rotations": [5], "lambda": [0.1]}},
            template_prefix="Texture_ToyModel_10000nm_gabor",
            random_seed=5423,
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_random_forest_2d_minkowsky(
        self,
        update_template: bool = False,
    ):
        # Random Forest method configuration:
        # Segmentation: Segmentation
        # Image: Texture_ToyModel_10000nm
        # Features: minkowsky
        common_successful_test_process(
            cls=self,
            method=RANDOM_FOREST_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="Texture_ToyModel_10000nm",
            features={"minkowsky": {"threshold": [0.0, 0.2, 0.4, 0.5, 0.6, 0.8, 1.0], "kernel_size": [0.1]}},
            template_prefix="Texture_ToyModel_10000nm_minkowsky",
            random_seed=5423,
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_random_forest_2d_variogram(
        self,
        update_template: bool = False,
    ):
        # Random Forest method configuration:
        # Segmentation: Segmentation
        # Image: Texture_ToyModel_10000nm
        # Features: variogram
        common_successful_test_process(
            cls=self,
            method=RANDOM_FOREST_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="Texture_ToyModel_10000nm",
            features={"variogram": {"kernel_size": [0.1]}},
            template_prefix="Texture_ToyModel_10000nm_variogram",
            random_seed=5423,
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_random_forest_2d_load_classifier(
        self,
        update_template: bool = False,
    ):
        # Random Forest method configuration:
        # Classifier: Texture_ToyModel_10000nm_1_Classifier
        # Image: Texture_ToyModel_10000nm
        common_successful_test_process(
            cls=self,
            method=RANDOM_FOREST_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            classifier_input="Classifier",
            image_name="Texture_ToyModel_10000nm",
            template_prefix="Texture_ToyModel_10000nm_Classifier",
            random_seed=5423,
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("Volumes", "MicroCTEnv"))
    @patch("commons.slicer.helpers.getCurrentEnvironment", lambda: NodeEnvironment.MICRO_CT)
    def test_pre_trained_microct_pore_unet(
        self,
        update_template: bool = False,
    ):
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Pore",
            pre_trained_model="U-net",
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            image_name="Texture_ToyModel_10000nm",
            template_prefix="Texture_ToyModel_10000nm_Pore_Unet",
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("Volumes", "MicroCTEnv"))
    def test_pre_trained_microct_basins_unet(
        self,
        update_template: bool = False,
    ):
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Basins",
            pre_trained_model="U-net",
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            image_name="Texture_ToyModel_10000nm",
            template_prefix="Texture_ToyModel_10000nm_Basins_Unet",
            update_template=update_template,
        )

        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Basins",
            pre_trained_model="U-net",
            project_file=MICROCT_BORDER_PROJECT_FILE,
            image_name="Input_volume",
            template_prefix="Basins_Unet",
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_pore_bayesian_3px(
        self,
        update_template: bool = False,
    ):
        # Random Forest method configuration:
        # Classifier: Poros Bayesian 3px
        # Image: Texture_ToyModel_10000nm
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Pore",
            pre_trained_model="Bayesian small kernel",
            project_file=QEMSCAN_PROJECT_FILE,
            image_name="A_5242.60m_PP - Cropped",
            template_prefix="A_5242.60m_PP - Cropped_Bayesian_3px",
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_pore_bayesian_7px(
        self,
        update_template: bool = False,
    ):
        # Random Forest method configuration:
        # Classifier: Poros Bayesian 3px
        # Image: Texture_ToyModel_10000nm
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Pore",
            pre_trained_model="Bayesian big kernel",
            project_file=QEMSCAN_PROJECT_FILE,
            image_name="A_5242.60m_PP - Cropped",
            template_prefix="A_5242.60m_PP - Cropped_Bayesian_7px",
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_carbonate_pore_unet(
        self,
        update_template: bool = False,
    ):
        """
        Carbonate Pore method configuration:
        Segmentation: Poros
        Image: A_5242.60m_PP - Cropped_Poros
        """
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Pore",
            pre_trained_model="Carbonate (U-net)",
            project_file=QEMSCAN_PROJECT_FILE,
            image_name="A_5242.60m_PP - Cropped",
            template_prefix="A_5242.60m_PP - Cropped_Carbonate_Poros",
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_carbonate_granular_unet(
        self,
        update_template: bool = False,
    ):
        """
        Carbonate Granular Texture method configuration:
        Segmentation: Multiphase Texture Fina
        Image: A_5242.60m_PP - Cropped_Textura Fina
        """
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Multiphase",
            pre_trained_model="Carbonate - Granular Texture (U-net)",
            project_file=QEMSCAN_PROJECT_FILE,
            image_name="A_5242.60m_PP - Cropped",
            extra_image1_name="A_5242.60m_PX - Cropped",
            template_prefix="A_5242.60m_PP - Cropped_Carbonate_Textura_Fina",
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_carbonate_complete_unet(
        self,
        update_template: bool = False,
    ):
        """
        Carbonate Multiphase method configuration:
        Classifier: Multiphase
        Image: A_5242.60m_PP - Cropped_Completo
        """
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Multiphase",
            pre_trained_model="Carbonate (U-net)",
            project_file=QEMSCAN_PROJECT_FILE,
            image_name="A_5242.60m_PP - Cropped",
            extra_image1_name="A_5242.60m_PX - Cropped",
            template_prefix="A_5242.60m_PP - Cropped_Carbonate_Completo",
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_carbonate_dense_unet(
        self,
        update_template: bool = False,
    ):
        """
        Carbonate Dense Texture method configuration:
        Classifier: Multiphase Textura Densa
        Image: A_5242.60m_PP - Cropped_Textura Densa
        """
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Multiphase",
            pre_trained_model="Carbonate - Dense Texture (U-net)",
            project_file=QEMSCAN_PROJECT_FILE,
            image_name="A_5242.60m_PP - Cropped",
            extra_image1_name="A_5242.60m_PX - Cropped",
            template_prefix="A_5242.60m_PP - Cropped_Carbonate_Textura_Densa",
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_siliciclastic_complete_unet(
        self,
        update_template: bool = False,
    ):
        """
        Siliciclastic Multiphase method configuration:
        Segmentation: Multiphase
        Image: numero_15_PP - Cropped_Siliciclastic_Completo
        """
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Multiphase",
            pre_trained_model="Siliciclastics (U-net)",
            project_file=QEMSCAN_PROJECT_FILE,
            image_name="numero_15_PP - Cropped",
            extra_image1_name="numero_15_PX - Cropped",
            template_prefix="numero_15_PP - Cropped_Siliciclastic_Completo",
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_siliciclastic_composed_unet(
        self,
        update_template: bool = False,
    ):
        """
        Siliciclastic Multiphase Composed method configuration:
        Segmentation: Multiphase
        Image: numero_15_PP - Cropped_Siliciclastic_Composed
        """
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Multiphase",
            pre_trained_model="Siliciclastics - Composed (U-net)",
            project_file=QEMSCAN_PROJECT_FILE,
            image_name="numero_15_PP - Cropped",
            extra_image1_name="numero_15_PX - Cropped",
            template_prefix="numero_15_PP - Cropped_Siliciclastic_Composed",
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_siliciclastic_pore_unet(
        self,
        update_template: bool = False,
    ):
        """
        Siliciclastic Pore method configuration:
        Segmentation: Pore
        Image: numero_15_PP - Cropped_Siliciclastic_Poro
        """
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Pore",
            pre_trained_model="Siliciclastics (U-net)",
            project_file=QEMSCAN_PROJECT_FILE,
            image_name="numero_15_PP - Cropped",
            extra_image1_name="numero_15_PX - Cropped",
            template_prefix="numero_15_PP - Cropped_Siliciclastic_Poro",
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_spurious_pores_removal(
        self,
        update_template: bool = False,
    ):
        # Pre-trained bayesian inference with spurious removal method configuration:
        # Classifier: Poros Bayesian 3px
        # Image: ABC-123_3126.65m_2.5x_TG_c1 - Cropped
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Pore",
            pre_trained_model="Bayesian small kernel",
            project_file=PORE_CLEANING_PROJECT_FILE,
            image_name="ABC-123_3126.65m_2.5x_TG_c1 - Cropped",
            template_prefix="ABC-123_3126.65m_2.5x_TG_c1 - Cropped_No_Spurious",
            update_template=update_template,
            remove_spurious=True,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_pore_resin_cleaning(
        self,
        update_template: bool = False,
    ):
        # Pre-trained bayesian inference with resin cleaning method configuration:
        # Classifier: Poros Bayesian 3px
        # Image: ABC-123_3126.65m_2.5x_TG_c1 - Cropped
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Pore",
            pre_trained_model="Bayesian small kernel",
            project_file=PORE_CLEANING_PROJECT_FILE,
            image_name="ABC-123_3126.65m_2.5x_TG_c1 - Cropped",
            template_prefix="ABC-123_3126.65m_2.5x_TG_c1 - Cropped_Clean_Resin",
            update_template=update_template,
            clean_resin=True,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_pore_resin_cleaning_px(
        self,
        update_template: bool = False,
    ):
        # Pre-trained bayesian inference with resin cleaning using PX method configuration:
        # Classifier: Poros Bayesian 3px
        # Image: ABC-123_3126.65m_2.5x_TG_c1 - Cropped
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Pore",
            pre_trained_model="Bayesian small kernel",
            project_file=PORE_CLEANING_PROJECT_FILE,
            image_name="ABC-123_3126.65m_2.5x_TG_c1 - Cropped",
            template_prefix="ABC-123_3126.65m_2.5x_TG_c1 - Cropped_Clean_Resin_PX",
            update_template=update_template,
            clean_resin=True,
            extra_cleaning_image_name="ABC-123_3126.65m_2.5x_TG_c2 - Cropped",
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_pore_resin_cleaning_smart_registration(
        self,
        update_template: bool = False,
    ):
        # Pre-trained bayesian inference with resin cleaning with smart registration method configuration:
        # Classifier: Poros Bayesian 3px
        # Image: ABC-123_3126.65m_2.5x_TG_c1 - Cropped
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Pore",
            pre_trained_model="Bayesian small kernel",
            project_file=PORE_CLEANING_PROJECT_FILE,
            image_name="ABC-123_3126.65m_2.5x_TG_c1 - Cropped_High_Misalignment",
            template_prefix="ABC-123_3126.65m_2.5x_TG_c1 - Cropped_Clean_Resin_Smart_Registration",
            update_template=update_template,
            clean_resin=True,
            extra_cleaning_image_name="ABC-123_3126.65m_2.5x_TG_c2 - Cropped",
            smart_registration=True,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_pore_resin_cleaning_px_as_input(
        self,
        update_template: bool = False,
    ):
        """
        Siliciclastic Pore with resin cleaning using PX method configuration:
        Segmentation: Pore
        Image: numero_15_PP - Cropped_Siliciclastic_Poro
        """
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Pore",
            pre_trained_model="Siliciclastics (U-net)",
            project_file=PORE_CLEANING_PROJECT_FILE,
            image_name="numero_11_10x_ST_c1 - Cropped",
            extra_image1_name="numero_11_10x_ST_c2 - Cropped",
            template_prefix="numero_11_10x_ST_c1 - Cropped_Silic_Clean_Resin",
            update_template=update_template,
            clean_resin=True,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_pore_cleaning_with_soi(
        self,
        update_template: bool = False,
    ):
        # Pre-trained bayesian inference with pore cleaning and SOI method configuration:
        # Classifier: Poros Bayesian 3px
        # Image: ABC-123_3126.65m_2.5x_TG_c1 - Cropped
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Pore",
            pre_trained_model="Bayesian small kernel",
            project_file=PORE_CLEANING_PROJECT_FILE,
            image_name="ABC-123_3126.65m_2.5x_TG_c1 - Cropped",
            soi_name="SOI",
            template_prefix="ABC-123_3126.65m_2.5x_TG_c1 - Cropped_Pore_Cleaning_With_SOI",
            update_template=update_template,
            remove_spurious=True,
            clean_resin=True,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_textural_structures_non_chunked(self, update_template: bool = False):
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Textural Structures",
            pre_trained_model="Optimistic (Mask R-CNN)",
            project_file=THIN_SECTION_INSTANCE_SEGMENTER_PROJECT_FILE,
            image_name="PX1",
            conf_thresh=50,
            nms_thresh=50,
            resize=1.0,
            calculate_statistics=True,
            template_folder="Templates/PX1 non_chunked",
            update_template=update_template,
            # compare_with_template=False,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_textural_structures_non_chunked_soi(self, update_template: bool = False):
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Textural Structures",
            pre_trained_model="Optimistic (Mask R-CNN)",
            project_file=THIN_SECTION_INSTANCE_SEGMENTER_PROJECT_FILE,
            soi_name="SOI",
            image_name="PX1",
            conf_thresh=50,
            nms_thresh=50,
            resize=1.0,
            calculate_statistics=True,
            template_folder="Templates/PX1 non_chunked wSOI",
            update_template=update_template,
            # compare_with_template=False,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_textural_structures_chunked(self, update_template: bool = False):
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Textural Structures",
            pre_trained_model="Optimistic (Mask R-CNN)",
            project_file=THIN_SECTION_INSTANCE_SEGMENTER_PROJECT_FILE,
            image_name="PX1",
            conf_thresh=50,
            nms_thresh=50,
            resize=1.0,
            chunk_size=250,
            chunk_overlap=50,
            calculate_statistics=True,
            template_folder="Templates/PX1 chunked",
            update_template=update_template,
            # compare_with_template=False,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_textural_structures_chunked_zero_overlap(self, update_template: bool = False):
        common_successful_test_process(
            cls=self,
            method=PRE_TRAINED_MODEL_LABEL,
            pre_trained_model_type="Textural Structures",
            pre_trained_model="Optimistic (Mask R-CNN)",
            project_file=THIN_SECTION_INSTANCE_SEGMENTER_PROJECT_FILE,
            image_name="PX1",
            conf_thresh=50,
            nms_thresh=50,
            resize=1.0,
            chunk_size=250,
            chunk_overlap=0,
            calculate_statistics=True,
            template_folder="Templates/PX1 chunked_zero_overlap",
            update_template=update_template,
            # compare_with_template=False,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_textural_structures_recommended_settings_non_chunked_scenario(self):
        instance_segmenter_recommended_settings_test_process(
            cls=self,
            project_file=THIN_SECTION_INSTANCE_SEGMENTER_PROJECT_FILE,
            image_name="PX1",
            conf_thresh=50,
            nms_thresh=50,
            resize=1.0,
            chunk_size=100,
            chunk_overlap=10,
            expected_chunk_size=250,
            auto_non_chunking_expected=True,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_pre_trained_thin_section_textural_structures_recommended_settings_chunked_scenario(self):
        instance_segmenter_recommended_settings_test_process(
            cls=self,
            project_file=THIN_SECTION_INSTANCE_SEGMENTER_PROJECT_FILE,
            image_name="PX1_big_spacing",
            conf_thresh=50,
            nms_thresh=50,
            resize=1.0,
            chunk_size=100,
            chunk_overlap=10,
            expected_chunk_size=3,
            auto_non_chunking_expected=False,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_bayesian_inference_2d_axes(
        self,
        update_template: bool = False,
    ):
        # Bayesian inference method configuration:
        # Segmentation: Segmentation
        # Image: Texture_ToyModel_10000nm
        # Kernel: Axes
        common_successful_test_process(
            cls=self,
            method=BAYESIAN_INFERENCE_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="Texture_ToyModel_10000nm",
            template_prefix="Texture_ToyModel_10000nm_bayesian_inference_axes",
            kernel_size="0.2",
            kernel_type="Axes",
            unsafe_memory_check=True,
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_bayesian_inference_2d_planes(
        self,
        update_template: bool = False,
    ):
        # Bayesian inference method configuration:
        # Segmentation: Segmentation
        # Image: Texture_ToyModel_10000nm
        # Kernel: Planes
        common_successful_test_process(
            cls=self,
            method=BAYESIAN_INFERENCE_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="Texture_ToyModel_10000nm",
            template_prefix="Texture_ToyModel_10000nm_bayesian_inference_planes",
            kernel_size="0.2",
            kernel_type="Planes",
            unsafe_memory_check=True,
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_bayesian_inference_2d_extra_channels(
        self,
        update_template: bool = False,
    ):
        # Bayesian inference method configuration:
        # Segmentation: Segmentation_Extra
        # Image: Texture_ToyModel_10000nm
        # Kernel: Planes
        common_successful_test_process(
            cls=self,
            method=BAYESIAN_INFERENCE_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            segmentation_name="Segmentation_Extra",
            image_name="Texture_ToyModel_10000nm",
            extra_image1_name="Texture_ToyModel_Extra1_10000nm",
            extra_image2_name="Texture_ToyModel_Extra2_10000nm",
            template_prefix="Texture_ToyModel_10000nm_bayesian_inference_extra",
            kernel_size="0.1",
            kernel_type="Planes",
            unsafe_memory_check=True,
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_bayesian_inference_2d_unsafe_memory_unchecked(
        self,
        update_template: bool = False,
    ):
        # Bayesian inference method configuration:
        # Segmentation: Segmentation
        # Image: Texture_ToyModel_10000nm
        # Kernel: Cubes
        common_successful_test_process(
            cls=self,
            method=BAYESIAN_INFERENCE_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_2D_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="Texture_ToyModel_10000nm",
            template_prefix="Texture_ToyModel_10000nm_bayesian_inference_planes",
            kernel_size="0.2",
            kernel_type="Cubes",
            unsafe_memory_check=False,
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_bayesian_inference_3d_axes(
        self,
        update_template: bool = False,
    ):
        # Bayesian inference method configuration:
        # Segmentation: Segmentation
        # Image: Texture3D_ToyModel_10000nm
        # Kernel: Axes
        common_successful_test_process(
            cls=self,
            method=BAYESIAN_INFERENCE_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_3D_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="Texture3D_ToyModel_10000nm",
            template_prefix="Texture3D_ToyModel_10000nm_bayesian_inference_axes",
            kernel_size="3",
            kernel_type="Axes",
            unsafe_memory_check=True,
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_bayesian_inference_3d_planes(
        self,
        update_template: bool = False,
    ):
        # Bayesian inference method configuration:
        # Segmentation: Segmentation
        # Image: Texture3D_ToyModel_10000nm
        # Kernel: Planes
        common_successful_test_process(
            cls=self,
            method=BAYESIAN_INFERENCE_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_3D_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="Texture3D_ToyModel_10000nm",
            template_prefix="Texture3D_ToyModel_10000nm_bayesian_inference_planes",
            kernel_size="3",
            kernel_type="Planes",
            unsafe_memory_check=True,
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    def test_bayesian_inference_3d_cubes(
        self,
        update_template: bool = False,
    ):
        # Bayesian inference method configuration:
        # Segmentation: Segmentation
        # Image: Texture3D_ToyModel_10000nm
        # Kernel: Cubes
        common_successful_test_process(
            cls=self,
            method=BAYESIAN_INFERENCE_METHOD_LABEL,
            project_file=TEXTURA_SINTETICO_3D_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="Texture3D_ToyModel_10000nm",
            template_prefix="Texture3D_ToyModel_10000nm_bayesian_inference_cubes",
            kernel_size="3",
            kernel_type="Cubes",
            unsafe_memory_check=True,
            update_template=update_template,
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    @patch("commons.slicer.helpers.getCurrentEnvironment", lambda: NodeEnvironment.THIN_SECTION)
    def test_cleaning_selection(self):
        cleaning_visibility_test_on_pre_trained(
            cls=self, shoud_be_visible_decider=lambda model_type: model_type == "Pore"
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("MicroCT", "MicroCTEnv"))
    @patch("commons.slicer.helpers.getCurrentEnvironment", lambda: NodeEnvironment.MICRO_CT)
    def test_cleaning_selection_must_be_hide_on_microct(self):
        cleaning_visibility_test_on_pre_trained(cls=self, shoud_be_visible_decider=lambda model_type: False)

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    @patch("commons.slicer.helpers.getCurrentEnvironment", lambda: NodeEnvironment.THIN_SECTION)
    def test_pre_trained_model_types_visible_on_thin_section(self):
        buttons_visibility_test_on_pre_trained(
            cls=self, shoud_be_visible_decider=lambda model_type: model_type != "Basins"
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("MicroCT", "MicroCTEnv"))
    @patch("commons.slicer.helpers.getCurrentEnvironment", lambda: NodeEnvironment.MICRO_CT)
    def test_pre_trained_model_types_visible_on_microct(self):
        buttons_visibility_test_on_pre_trained(
            cls=self, shoud_be_visible_decider=lambda model_type: model_type in ["Pore", "Basins"]
        )

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    @patch("commons.slicer.helpers.getCurrentEnvironment", lambda: NodeEnvironment.THIN_SECTION)
    def test_entry_on_user_classifier_must_have_three_inputs(self):
        create_classifier_radio_button = self._widgets["create_classifier_radio_button"]
        load_classifier_radio_button = self._widgets["load_classifier_radio_button"]
        user_classifier_radio_button = self._widgets["user_classifier_radio_button"]

        single_shot_input = self._widgets["single_shot_input"]
        extra_image_1_combo_box = self._widgets["extra_image_1_combo_box"]
        extra_image_2_combo_box = self._widgets["extra_image_2_combo_box"]

        apply_button = self._widgets["apply_button"]

        self._module_widget.enter()

        create_classifier_radio_button.setChecked(True)
        user_classifier_radio_button.setChecked(False)
        load_classifier_radio_button.setChecked(False)
        self.assertTrue(apply_button.enabled is False)

        self.assertTrue(
            single_shot_input.referenceLabel.text.strip() == "Input volume #1:",
            f"Expected 'Input volume #1:' but got {single_shot_input.referenceLabel.text}",
        )
        self.assertTrue(extra_image_1_combo_box.visible)
        self.assertTrue(extra_image_2_combo_box.visible)

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    @patch("commons.slicer.helpers.getCurrentEnvironment", lambda: NodeEnvironment.THIN_SECTION)
    def test_input_visibility_on_pre_trained_mode(self):
        create_classifier_radio_button = self._widgets["create_classifier_radio_button"]
        load_classifier_radio_button = self._widgets["load_classifier_radio_button"]

        inputs_selector = self._widgets["single_shot_input"]

        self._module_widget.enter()

        # Start with "Load classifier" selected, annotation inputs should be hidden
        load_classifier_radio_button.setChecked(True)
        self.assertFalse(inputs_selector.segmentationLabel.visible)
        self.assertFalse(inputs_selector.mainInput.visible)
        self.assertFalse(inputs_selector.segmentsContainerWidget.visible)

        # Switch to "Create classifier", annotation inputs should appear
        create_classifier_radio_button.setChecked(True)
        self.assertTrue(inputs_selector.segmentationLabel.visible)
        self.assertTrue(inputs_selector.mainInput.visible)
        self.assertTrue(inputs_selector.segmentsContainerWidget.visible)

    @patch("slicer.modules.AppContextInstance.modules.currentWorkingDataType", ("ThinSection", "ThinSectionEnv"))
    @patch("commons.slicer.helpers.getCurrentEnvironment", lambda: NodeEnvironment.THIN_SECTION)
    def test_input_visibility_on_user_classifier(self):
        create_classifier_radio_button = self._widgets["create_classifier_radio_button"]
        user_classifier_radio_button = self._widgets["user_classifier_radio_button"]

        single_shot_input = self._widgets["single_shot_input"]
        extra_image_1_combo_box = self._widgets["extra_image_1_combo_box"]
        extra_image_2_combo_box = self._widgets["extra_image_2_combo_box"]
        inputs_selector = self._widgets["single_shot_input"]

        self._module_widget.enter()

        # Select "User classifier"
        user_classifier_radio_button.setChecked(True)

        # Check visibility and labels for input volumes
        self.assertTrue(single_shot_input.visible)
        self.assertTrue(extra_image_1_combo_box.visible)
        self.assertTrue(extra_image_2_combo_box.visible)
        self.assertEqual(single_shot_input.referenceLabel.text.strip(), "Input volume #1:")

        # Check that annotation input is hidden
        self.assertFalse(inputs_selector.segmentationLabel.visible)
        self.assertFalse(inputs_selector.mainInput.visible)
        self.assertFalse(inputs_selector.segmentsContainerWidget.visible)

        # Switch to "Create classifier", annotation inputs should appear
        create_classifier_radio_button.setChecked(True)
        self.assertTrue(inputs_selector.segmentationLabel.visible)
        self.assertTrue(inputs_selector.mainInput.visible)
        self.assertTrue(inputs_selector.segmentsContainerWidget.visible)

    def generate_random_forest_2d_raw(self):
        self.test_random_forest_2d_raw(update_template=True)

    def generate_random_forest_2d_raw_keep_features(self):
        self.test_random_forest_2d_raw_keep_features(update_template=True)

    def generate_random_forest_2d_quantized(self):
        self.test_random_forest_2d_quantized(update_template=True)

    def generate_random_forest_2d_petrobras(self):
        self.test_random_forest_2d_petrobras(update_template=True)

    def generate_random_forest_2d_gaussian(self):
        self.test_random_forest_2d_gaussian(update_template=True)

    def generate_random_forest_2d_gaussian_keep_features(self):
        self.test_random_forest_2d_gaussian_keep_features(update_template=True)

    def generate_random_forest_2d_winvar(self):
        self.test_random_forest_2d_winvar(update_template=True)

    def generate_random_forest_2d_gabor(self):
        self.test_random_forest_2d_gabor(update_template=True)

    def generate_random_forest_2d_minkowsky(self):
        self.test_random_forest_2d_minkowsky(update_template=True)

    def generate_random_forest_2d_variogram(self):
        self.test_random_forest_2d_variogram(update_template=True)

    def generate_random_forest_2d_load_classifier(self):
        self.test_random_forest_2d_load_classifier(update_template=True)

    def generate_pre_trained_microct_pore_unet(self):
        self.test_pre_trained_microct_pore_unet(update_template=True)

    def generate_pre_trained_microct_basins_unet(self):
        self.test_pre_trained_microct_basins_unet(update_template=True)

    def generate_pre_trained_thin_section_pore_bayesian_3px(self):
        self.test_pre_trained_thin_section_pore_bayesian_3px(update_template=True)

    def generate_pre_trained_thin_section_pore_bayesian_7px(self):
        self.test_pre_trained_thin_section_pore_bayesian_7px(update_template=True)

    def generate_pre_trained_thin_section_carbonate_pore_unet(self):
        self.test_pre_trained_thin_section_carbonate_pore_unet(update_template=True)

    def generate_pre_trained_thin_section_carbonate_granular_unet(self):
        self.test_pre_trained_thin_section_carbonate_granular_unet(update_template=True)

    def generate_pre_trained_thin_section_carbonate_complete_unet(self):
        self.test_pre_trained_thin_section_carbonate_complete_unet(update_template=True)

    def generate_pre_trained_thin_section_carbonate_dense_unet(self):
        self.test_pre_trained_thin_section_carbonate_dense_unet(update_template=True)

    def generate_pre_trained_thin_section_siliciclastic_complete_unet(self):
        self.test_pre_trained_thin_section_siliciclastic_complete_unet(update_template=True)

    def generate_pre_trained_thin_section_siliciclastic_composed_unet(self):
        self.test_pre_trained_thin_section_siliciclastic_composed_unet(update_template=True)

    def generate_pre_trained_thin_section_siliciclastic_pore_unet(self):
        self.test_pre_trained_thin_section_siliciclastic_pore_unet(update_template=True)

    def generate_pre_trained_thin_section_textural_structures_non_chunked(self):
        self.test_pre_trained_thin_section_textural_structures_non_chunked(update_template=True)

    def generate_pre_trained_thin_section_textural_structures_non_chunked_soi(self):
        self.test_pre_trained_thin_section_textural_structures_non_chunked_soi(update_template=True)

    def generate_pre_trained_thin_section_textural_structures_chunked(self):
        self.test_pre_trained_thin_section_textural_structures_chunked(update_template=True)

    def generate_pre_trained_thin_section_textural_structures_chunked_zero_overlap(self):
        self.test_pre_trained_thin_section_textural_structures_chunked_zero_overlap(update_template=True)

    def generate_bayesian_inference_2d_axes(self):
        self.test_bayesian_inference_2d_axes(update_template=True)

    def generate_bayesian_inference_2d_planes(self):
        self.test_bayesian_inference_2d_planes(update_template=True)

    def generate_bayesian_inference_2d_extra_channels(self):
        self.test_bayesian_inference_2d_extra_channels(update_template=True)

    def generate_bayesian_inference_2d_unsafe_memory_unchecked(self):
        self.test_bayesian_inference_2d_unsafe_memory_unchecked(update_template=True)

    def generate_bayesian_inference_3d_axes(self):
        self.test_bayesian_inference_3d_axes(update_template=True)

    def generate_bayesian_inference_3d_planes(self):
        self.test_bayesian_inference_3d_planes(update_template=True)

    def generate_bayesian_inference_3d_cubes(self):
        self.test_bayesian_inference_3d_cubes(update_template=True)
