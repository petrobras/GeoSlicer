import hashlib
import requests

urls = [
    "https://kitware.github.io/itk-vtk-viewer/app/itkVtkViewerCDN.js",
    "https://unpkg.com/vtk.js@31.0.0/vtk.js",
]

for url in urls:
    response = requests.get(url)
    file_content = response.content

    hash_sha256 = hashlib.sha256(file_content).hexdigest()

    print(f"{url}: {hash_sha256}")
