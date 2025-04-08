import os
import pickle

import numpy as np
import pandas as pd
from sklearn.cluster import MeanShift

from ltrace.algorithms.measurements import LabelStatistics2D
from workflow.commons import addUnitsToDataFrameParameters, DESCRIPTIVE_STATISTICS


class SheetExporter:

    ## SheetExporter: Geração de planilhas contendo propriedades e estatísticas calculadas

    # Salva em planilha as propriedades geológicas calculadas e estatísticas relacionadas para cada
    # imagem. A versão AllStats reúne as propriedades de cada instância individualmente, enquanto a
    # versão GroupsStats as agrupa por similaridade de tamanho e dedica diferentes páginas para
    # diferentes estatísticas descritivas (média, mediana, desvio padrão, mínimo e máximo) para cada
    # grupo.

    # No caso dos poros, os grupos são calculados de forma não-supervisionada, enquanto que para os
    # oóides são pré-definidos com base na escala granulométrica de Udden-Wentworth.

    def __init__(self, temporary):
        persistence_prefix = "tmp_" if temporary else ""
        self.temporary = temporary
        self.stats_sheet_prefix = f"{persistence_prefix}AllStats"

    def _save_all_stats_sheet(self, image_name, report_file_path, output_dir, instance_type):
        unnecessary_attrs = ["label", "voxelCount", "pore_size_class"]
        if os.path.exists(report_file_path):
            with open(report_file_path, "rb") as report:
                df = pickle.load(report)
        else:
            df = pd.DataFrame([], columns=LabelStatistics2D.ATTRIBUTES)
            df = addUnitsToDataFrameParameters(df)

        image_output_dir = os.path.join(output_dir, image_name)
        os.makedirs(image_output_dir, exist_ok=True)
        df = df.drop(unnecessary_attrs, axis=1)
        df.to_excel(
            os.path.join(image_output_dir, f"{self.stats_sheet_prefix}_{image_name}_{instance_type}.xlsx"), index=False
        )

        return df

    def _group_instances_and_save_stats_sheet(self, image_name, df, output_dir, instance_type, groups, supergroups):
        def predict(value, groups):
            for group_label, value_range in groups["scales"].items():
                if value_range[0] <= value < value_range[1]:
                    return group_label

        if not df.empty:
            if not groups:
                property_values = df["area (mm^2)"].values
                property_values = property_values.reshape(*property_values.shape, 1)

                ms = MeanShift()
                pred_groups = ms.fit_predict(property_values) + 1

                group_labels = range(1, max(pred_groups) + 1)
            else:
                property_values = df[groups["property"]].values
                pred_groups = np.array([predict(value, groups) for value in property_values])
                group_labels = list(groups["scales"].keys())
        else:
            group_labels = []

        with pd.ExcelWriter(
            os.path.join(output_dir, image_name, f"GroupsStats_{image_name}_{instance_type}.xlsx")
        ) as sheet_writer:
            new_cols = ["group", "quantity", "percentage (%)"]
            if supergroups:
                new_cols.insert(1, "supergroup")

            for statistic_func, sheet_name in DESCRIPTIVE_STATISTICS.items():
                sheet = pd.DataFrame([], columns=new_cols + list(df.columns))
                for g in group_labels:
                    g_indexes = np.where(pred_groups == g)[0]

                    statistics = getattr(df.iloc[g_indexes], statistic_func)()
                    statistics = statistics.fillna(0)

                    statistics["group"] = g
                    if supergroups:
                        statistics["supergroup"] = supergroups[g]
                    statistics["quantity"] = len(g_indexes)
                    statistics["percentage (%)"] = 100 * len(g_indexes) / len(property_values)

                    if sheet.empty:
                        sheet = statistics.to_frame().T.copy()
                    else:
                        sheet = pd.concat([sheet, statistics.to_frame().T], ignore_index=True)

                sheet = sheet.sort_values(by=["quantity", "area (mm^2)"], ascending=[False, True])
                sheet = sheet[new_cols + list(sheet.drop(new_cols, axis=1).columns)]
                sheet.to_excel(sheet_writer, sheet_name=sheet_name, index=False)

    def run(self, image_file_path, report_file_path, output_dir, instance_type="pores", groups=None, supergroups=None):
        image_name = os.path.splitext(os.path.basename(image_file_path))[0]

        df = self._save_all_stats_sheet(image_name, report_file_path, output_dir, instance_type)
        if not self.temporary:
            self._group_instances_and_save_stats_sheet(image_name, df, output_dir, instance_type, groups, supergroups)
