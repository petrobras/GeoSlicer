# Installation Guide

Below are the steps for installing GeoSlicer. Pay close attention to the highlighted items, as they are tips to overcome some common situations.

## Prerequisites

GeoSlicer runs on any Windows or Linux computer released in the last 5 years. Older computers may work (depending mainly on graphics capabilities). The **minimum** requirements are:

- Operating System: Windows 10 or Ubuntu 20.04 LTS
- RAM: 8 GB
- Screen resolution: 1024x768 (we recommend 1280x1024 or higher)
- Video card: 4 GB RAM, OpenGL 3.2 support (we recommend at least double the size of the largest data to be used)
- Storage: > 15GB free disk space. We recommend an SSD for better performance.

!!! tip
    Prefer local SSD drives, avoid network drives (NAS). Have more than 15GB free to store the software and the data used in the experiment.

## Installation

#### 1. Preparation

Choose a drive for installation, preferably local SSD drives.

!!! tip
    (Optional) Install the 7zip tool. The GeoSlicer installer detects its presence and uses it to decompress the installation more efficiently. As GeoSlicer is a large application, decompression is a time-consuming process and will take longer if performed by the native Windows tool.

#### 2. Download

##### Public version

Download the most up-to-date version from the `Releases` page of our [public repository](https://github.com/petrobras/GeoSlicer/releases). If you are interested in creating your own modules, follow the guidelines on the [Development](/Development/BuildingGeoSlicer.md) page.

##### Private version

Learn about the private version in [this article](PrivateVersion.md).

If you have access to a private environment with the closed version of GeoSlicer,
such as Petrobras, you can download it via LTrace's [sharepoint](https://petrobrasbr.sharepoint.com.mcas.ms/teams/LTRACE/SitePages/Home.aspx) or directly from Teams by contacting a member of the LTrace team. 

#### 3. Installation

Execute the GeoSlicer installer (GeoSlicer-*.exe) and it will ask for the installation location. Select a location on the drive chosen in the preparation step (Step 1) and click Extract.

Then the file decompression begins, and you can monitor the installation progress. If you have installed 7zip, a screen similar to this will appear. Otherwise, it will be the operating system's native progress bar.

#### 3. Execution

After the installation is complete, go to the folder chosen in the previous step, and run GeoSlicer.exe. This first execution configures the application.

During the first execution, after completing the application configuration, GeoSlicer will restart to finalize the installation. In versions below 2.5, this step is automatic, but don't worry, after this restart the application is ready to be used.