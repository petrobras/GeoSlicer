try:
    from . import pdefs
except ImportError:
    pdefs = None

MODELS_DOWNLOAD_LINK = "https://www.ltrace.com.br/geoslicer/download-ai-models/"


def get_model_download_links() -> dict:
    links = {}

    links["Public"] = MODELS_DOWNLOAD_LINK
    if pdefs is not None:
        plinks = pdefs.get_model_download_links()
        links.update(plinks)

    return links
