try:
    from . import pdefs
except:
    pdefs = None

MODELS_DOWNLOAD_LINK = "https://www.ltrace.com.br/geoslicer/download-ai-models/"


def get_model_download_links() -> dict:
    links = {}

    links["Public"] = MODELS_DOWNLOAD_LINK
    if pdefs is not None:
        links["Petrobras"] = pdefs.MODELS_DOWNLOAD_LINK

    return links
