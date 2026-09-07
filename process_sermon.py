import datetime
import json
import os
import subprocess
import sys
from xml.etree import ElementTree as ET

CHANNEL_URL = "https://www.youtube.com/@cbtrebova/streams"
FEED_FILE = "feed.xml"
REPO_NAME = os.environ.get("GITHUB_REPOSITORY", "sarkablasko/cbtrebova-youtube-to-spotify")


def get_ytdlp_base_cmd():
    """Zakladni parametry s podporou JS challenge a cookies."""
    cmd = [
        "yt-dlp",
        "--js-runtimes", "node",
        "--remote-components", "ejs:github"
    ]
    if os.path.exists("cookies.txt"):
        cmd.extend(["--cookies", "cookies.txt"])
    return cmd

def run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Chyba prikazu: {res.stderr}", file=sys.stderr)
        sys.exit(res.returncode)
    return res.stdout.strip()


def get_latest_stream_id():
    cmd = get_ytdlp_base_cmd() + [
        "--flat-playlist",
        "--dump-json",
        "--playlist-end", "1",
        CHANNEL_URL
    ]
    out = run(cmd)
    if not out:
        raise RuntimeError("Nenalezen zadny stream.")
    return json.loads(out)["id"]


def process_media(video_id):
    info_cmd = get_ytdlp_base_cmd() + ["-j", f"https://www.youtube.com/watch?v={video_id}"]
    info = json.loads(run(info_cmd))

    title = info.get("title", f"Kázání {datetime.date.today()}")
    description = info.get("description", "")
    chapters = info.get("chapters", [])
    thumb_url = info.get("thumbnail")

    start_time, end_time = None, None
    for ch in chapters:
        ch_name = ch.get("title", "").lower()
        if any(w in ch_name for w in ["kázání", "kazani", "slovo"]):
            start_time = ch.get("start_time")
            end_time = ch.get("end_time")
            break

    raw_audio = f"raw_{video_id}.mp3"
    dl_cmd = get_ytdlp_base_cmd() + [
        "-x",
        "--audio-format", "mp3",
        "-o", raw_audio,
        f"https://www.youtube.com/watch?v={video_id}"
    ]
    run(dl_cmd)

    final_audio = f"sermon_{video_id}.mp3"
    ff_audio_cmd = ["ffmpeg", "-y", "-i", raw_audio]
    if start_time is not None:
        ff_audio_cmd.extend(["-ss", str(start_time)])
    if end_time is not None:
        ff_audio_cmd.extend(["-to", str(end_time)])

    ff_audio_cmd.extend([
        "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
        "-ac", "1",
        "-b:a", "128k",
        final_audio
    ])
    run(ff_audio_cmd)

    if os.path.exists(raw_audio):
        os.remove(raw_audio)

    dur = int(float(
        run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
             final_audio])))
    size = os.path.getsize(final_audio)

    cover_file = f"cover_{video_id}.jpg"
    if thumb_url:
        ff_img_cmd = [
            "ffmpeg", "-y", "-i", thumb_url,
            "-vf",
            "split[a][b];[a]scale=3000:3000:flags=lanczos,boxblur=25:5[bg];[b]scale=3000:-1:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2",
            "-q:v", "2",
            cover_file
        ]
        run(ff_img_cmd)
    else:
        cover_file = None

    return final_audio, cover_file, title, description, size, dur


def update_feed(audio_file, cover_file, title, description, size, dur, release_tag):
    ET.register_namespace("itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
    tree = ET.parse(FEED_FILE)
    channel = tree.find("channel")

    for item in channel.findall("item"):
        guid = item.find("guid")
        if guid is not None and guid.text == audio_file:
            print("Epizoda jiz existuje.")
            return False

    item = ET.Element("item")
    ET.SubElement(item, "title").text = title
    desc_elem = ET.SubElement(item, "description")
    desc_elem.text = description if description else title
    ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = audio_file
    ET.SubElement(item, "pubDate").text = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S +0000")

    media_url = f"https://github.com/{REPO_NAME}/releases/download/{release_tag}/{audio_file}"
    ET.SubElement(item, "enclosure", {"url": media_url, "length": str(size), "type": "audio/mpeg"})

    dur_elem = ET.SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}duration")
    dur_elem.text = str(dur)

    if cover_file:
        img_url = f"https://github.com/{REPO_NAME}/releases/download/{release_tag}/{cover_file}"
        ET.SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}image", {"href": img_url})

    first_item = channel.find("item")
    if first_item is not None:
        channel.insert(list(channel).index(first_item), item)
    else:
        channel.append(item)

    tree.write(FEED_FILE, encoding="utf-8", xml_declaration=True)
    return True


if __name__ == "__main__":
    vid = get_latest_stream_id()
    tag = f"ep-{datetime.date.today().strftime('%Y%m%d')}"
    mp3, cover, ep_title, ep_desc, ep_size, ep_dur = process_media(vid)
    update_feed(mp3, cover, ep_title, ep_desc, ep_size, ep_dur, tag)
    print(f"OUTPUT_TAG={tag}")
    print(f"OUTPUT_FILE={mp3}")
    if cover:
        print(f"OUTPUT_COVER={cover}")