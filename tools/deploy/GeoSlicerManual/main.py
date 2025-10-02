from pathlib import Path


def define_env(env):
    @env.macro
    def video(name: str, caption: str = None):
        extension = name.split(".")[-1].lower()

        page = env.variables["page"]
        page_dir = Path(page.file.src_path).parent
        depth = len(page_dir.parts)
        relative_path_to_videos = Path(*[".."] * depth) / "assets" / "videos"
        video_path = (relative_path_to_videos / name).as_posix()

        video_html = (
            f'<video controls width="100%">'
            f'  <source src="{video_path}" type="video/{extension}">'
            f"  Your browser does not support the video tag."
            f"</video>"
        )

        if caption:
            return (
                f'<figure class="video-container">'
                f"  {video_html}"
                f"  <figcaption>{caption}</figcaption>"
                f"</figure>"
            )
        else:
            return video_html
