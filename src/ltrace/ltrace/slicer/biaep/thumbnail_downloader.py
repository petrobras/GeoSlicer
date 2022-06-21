from enum import Enum
from pathlib import Path
from typing import Tuple, Union
from ltrace.slicer.cache.cache_files import CacheFiles

import biaep
import logging
import pandas as pd
import shutil
import tempfile
import threading


class DownloadState(Enum):
    NOT_INITIALIZED = 0
    DOWNLOADING = 1
    FINISHED = 2
    CANCELED = 3
    ERROR = 4


THUMBNAIL_FILE_PATH_LABEL = "thumbnail_file_path"


class ThumbnailDownloader:
    def __init__(
        self,
        biaep_session: biaep.BIAEP,
        df: pd.DataFrame,
        cache_root_directory: Union[Path, str],
        batch_size: int = 20,
        thumbnail_size: Tuple[int, int] = (900, 900),
    ) -> None:
        super().__init__()
        self._cache_files = CacheFiles(name="thumbnails", expiration_days=30, root_directory_path=cache_root_directory)
        self._session = biaep_session
        self._df = df
        self._state = DownloadState.NOT_INITIALIZED
        self._batch_size = batch_size
        self._thumbnail_size = thumbnail_size
        self._thread = None
        self._output = None

        # Callbacks
        self.on_download_batch_finished_callback = lambda df: None
        self.on_download_process_finished_callback = lambda df: None

    @property
    def output(self) -> Union[pd.DataFrame, None]:
        """Returns the pandas.DataFrame containing the 'id', 'name' and 'THUMBNAIL_FILE_PATH_LABEL' informations related to the last download process.

        Returns:
            Union[pd.DataFrame, None]: pd.DataFrame if a download process was made, otherwise None.
        """
        return self._output

    @property
    def df(self) -> pd.DataFrame:
        return self._df

    @df.setter
    def df(self, new_df) -> None:
        if self.state == DownloadState.DOWNLOADING:
            raise RuntimeError("Can't change input DataFrame during download process!")

        self._df = new_df

    @property
    def batch_size(self) -> int:
        return self._batch_size

    @batch_size.setter
    def batch_size(self, new_batch_size) -> None:
        if self.state == DownloadState.DOWNLOADING:
            raise RuntimeError("Can't change batch size during download process!")

        self._batch_size = new_batch_size

    @property
    def thumbnail_size(self) -> Tuple[int, int]:
        return self._thumbnail_size

    @thumbnail_size.setter
    def thumbnail_size(self, new_thumbnail_size: Tuple[int, int]) -> None:
        if self.state == DownloadState.DOWNLOADING:
            raise RuntimeError("Can't change thumbnail size during download process!")

        self._thumbnail_size = new_thumbnail_size

    @property
    def state(self) -> DownloadState:
        return self._state

    def start(self, asynchronous=False) -> None:
        """Start download process

        Args:
            asynchronous (bool, optional): Handle download process in a new thread if True. Defaults to True.

        Raises:
            RuntimeError: When download process is already running.
            RuntimeError: When defined DataFrame is invalid.
        """
        if self.state == DownloadState.DOWNLOADING:
            raise RuntimeError("Donwload process already running!")

        if self._df is None or self._df.empty:
            self.state == DownloadState.ERROR
            message = "The DataFrameinput is empty."
            logging.info(message)
            raise RuntimeError(message)
        if asynchronous:
            self._thread = threading.Thread(target=self._download_thumbnails)
            self._thread.start()
        else:
            self._download_thumbnails()

    def _download_thumbnails(
        self, temporary_download_directory_path: Path = Path(tempfile.TemporaryDirectory().name)
    ) -> None:
        """Download process handler. Download thumbnails in batch sizes, based on the defined class atributtes.
           At the end of the download process, and the end of each batch download process, the callback methods
           'on_download_batch_finished_callback' and 'on_download_process_finished_callback' will be called with the respectively results.

        Args:
            temporary_download_directory_path (Path, optional): The path to store downloaded thumbnails temporarily. Defaults to Path(tempfile.TemporaryDirectory().name).

        Raises:
            RuntimeError: When download process is already running.
            RuntimeError: When defined DataFrame is invalid.
        """
        if self.state == DownloadState.DOWNLOADING:
            message = "Thumbnails download already in progress..."
            logging.info(message)
            raise RuntimeError(message)

        if self._df is None or self._df.empty:
            message = "The input DataFrame is empty. Please insert a valid DataFrame."
            logging.info(message)
            raise RuntimeError(message)

        self._state = DownloadState.DOWNLOADING

        input_df = self._df.copy()

        if not temporary_download_directory_path.exists():
            temporary_download_directory_path.mkdir(parents=True, exist_ok=True)

        for idx in range(0, input_df.shape[0], self._batch_size):
            start = idx
            end = idx + self._batch_size
            batch_df = input_df[start:end].reset_index(drop=True)
            batch_df_with_cache = self.get_thumbnails_from_cache(df=batch_df)
            batch_df_with_cache.dropna(inplace=True, subset=[THUMBNAIL_FILE_PATH_LABEL])
            batch_df_without_cache = (
                pd.merge(batch_df, batch_df_with_cache, on=list(batch_df.columns), how="outer", indicator=True)
                .query("_merge != 'both'")
                .drop("_merge", axis=1)
                .drop(THUMBNAIL_FILE_PATH_LABEL, axis=1)
                .reset_index(drop=True)
            )
            try:
                self._session.download_thumbnail(
                    df=batch_df_without_cache,
                    dirname=temporary_download_directory_path.as_posix(),
                    image_width=self._thumbnail_size[0],
                    image_height=self._thumbnail_size[1],
                )
            except Exception as error:
                logging.debug(f"Error during attempt to download the thumbnails: {error}")

            if self.state == DownloadState.CANCELED:
                break

            for file in temporary_download_directory_path.glob("*"):
                self._cache_files.add_file(file)

            # Handle batch download process finished
            cached_batch_df = self.get_thumbnails_from_cache(df=batch_df)
            self._on_download_batch_finished(cached_batch_df)

        shutil.rmtree(temporary_download_directory_path)

        if self.state == DownloadState.CANCELED:
            return

        self._output = self.get_thumbnails_from_cache(df=input_df)

        # Handle download process finished
        self._on_download_process_finished(self._output)

    def cancel(self) -> None:
        """Cancel download process.

        Raises:
            RuntimeError: When download process is not running.
        """
        if self.state is not DownloadState.DOWNLOADING:
            raise RuntimeError("No download process running!")

        self._state = DownloadState.CANCELED

        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def _on_download_process_finished(self, df: pd.DataFrame) -> None:
        """Handles the finished download process. Calls the related callback for external signalization.

        Args:
            df (pd.DataFrame): the DataFrame containing all the downloaded thumbnails file path.

        Raises:
            RuntimeError: When download process is not running.
        """
        if self.state is not DownloadState.DOWNLOADING:
            raise RuntimeError("No download process running!")

        self._state = DownloadState.FINISHED

        if self._thread is not None:
            self._thread = None

        self.on_download_process_finished_callback(df)

    def _on_download_batch_finished(self, df: pd.DataFrame) -> None:
        """Handles the finished batch download process. Calls the related callback for external signalization.

        Args:
            df (pd.DataFrame): the DataFrame containing the downloaded thumbnails file path from the related batch.

        Raises:
            RuntimeError: When download process is not running.
        """
        if self.state is not DownloadState.DOWNLOADING:
            raise RuntimeError("No download process running!")

        self.on_download_batch_finished_callback(df)

    def get_thumbnails_from_cache(self, df: pd.DataFrame) -> pd.DataFrame:
        """Retrieve the thumbnails that are already in cache, related to the input DataFrame names.

        Args:
            df (pd.DataFrame): The input DataFrame containing the images related name.

        Raises:
            RuntimeError: If the input DataFrame is invalid.

        Returns:
            pd.DataFrame: The DataFrame containing the already downloaded thumbnails file path.
        """
        if "name" not in list(df.columns):
            raise RuntimeError("Input DataFrame doesn't contain the required column ('name')")

        if df is None or df.empty:
            return df

        data = {"name": [], THUMBNAIL_FILE_PATH_LABEL: []}

        for name in list(df["name"]):
            thumbnail_filename = self._get_thumbnail_file_name_pattern(name=Path(name).stem, extension=None)
            cached_files = self._cache_files.is_file_cached(thumbnail_filename, check_extension=False)

            if not cached_files:
                continue

            data["name"].append(name)
            data[THUMBNAIL_FILE_PATH_LABEL].append(cached_files[0].as_posix())

        data_df = pd.DataFrame.from_dict(data)
        # join data to related columns from the input DataFrame
        output_df = pd.merge(df, data_df, on="name", how="left")
        # output_df.dropna(inplace=True, subset=[THUMBNAIL_FILE_PATH_LABEL])
        return output_df

    def _get_thumbnail_file_name_pattern(self, name: str, extension: str = None) -> str:
        """Retrieve the thumbnail file name pattern based on the input's name string.

        Args:
            name (str): the input's name string.
            extension (str, optional): The file extension. Defaults to None.

        Returns:
            str: the expected thumbnail file name.
        """
        width, height = self._thumbnail_size
        filename = "{}-thumb-{}-{}".format(name, width, height)
        if extension:
            filename = f"{filename}.{extension}"

        return filename
