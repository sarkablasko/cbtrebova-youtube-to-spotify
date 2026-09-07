import datetime
import json
import os
import subprocess
import sys
from xml.etree import ElementTree as ET

# Konfigurace
CHANNEL_URL = "https://www.youtube.com/@cbtrebova/streams"
FEED_FILE = "feed.xml"
REPO_NAME = os.environ.get("GITHUB_REPOSITORY", "<VASE_UZIVATELSKE_JMENO>/cbtrebova-podcast")


def run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Chyba: {res.stderr}", file=sys.stderr)
        sys.exit(res.returncode)
    return res.stdout.strip()


def get_latest_stream_id():
    cmd = ["yt-dlp", "--flat-playlist", "--dump-json", "--playlist-end", "1", CHANNEL_URL]
    out = run(cmd)
    if not out:
        raise RuntimeError("Nenalezen zadny zaznam streamu.")
    return json.loads(out)["id"]


def process_audio(video_id):
    info = json.loads(run(["yt-dlp", "-j", f"https://www.youtube.com/watch?v={video_id}"]))
    title = info.get("title", f"Kázání {datetime.date.today()}")
    chapters = info.get("chapters", [])

    # Detekce casu zacatku a konce kazani z popisku
    start_time, end_time = None, None
    for ch in chapters:
        name = ch.get("title", "").lower()
        if any(w in name for w in ["kázání", "kazani", "slovo"]):
            start_time = ch.get("start_time")
            end_time = ch.get("end_time")
            break

    # Stazeni suroveho audia
    raw_file = f"raw_{video_id}.mp3"
    run(["yt-dlp", "-x", "--audio-format", "mp3", "-o", raw_file, f"https://www.youtube.com/watch?v={video_id}"])

    # Orez a normalizace zvuku (-16 LUFS, Mono, 128 kbps)
    final_file = f"sermon_{video_id}.mp3"
    ff_cmd = ["ffmpeg", "-y", "-i", raw_file]
    if start_time is not None:
        ff_cmd.extend(["-ss", str(start_time)])
    if end_time is not None:
        ff_cmd.extend(["-to", str(end_time)])

    ff_cmd.extend([
        "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
        "-ac", "1",
        "-b:a", "128k",
        final_file
    ])
    run(ff_cmd)

    if os.path.exists(raw_file):
        os.remove(raw_file)

    # Zjisteni delky a velikosti
    dur = int(float(
        run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
             final_file])))
    size = os.path.getsize(final_file)
    return final_file, title, size, dur


def update_feed(audio_file, title, size, dur, release_tag):
    ET.register_namespace("itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
    tree = ET.parse(FEED_FILE)
    channel = tree.find("channel")

    # Kontrola duplicity podle souboru
    for item in channel.findall("item"):
        guid = item.find("guid")
        if guid is not None and guid.text == audio_file:
            print("Epizoda jiz ve feedu existuje.")
            return False

    item = ET.Element("item")
    ET.SubElement(item, "title").text = title
    ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = audio_file
    ET.SubElement(item, "pubDate").text = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S +0000")

    media_url = f"https://github.com/{REPO_NAME}/releases/download/{release_tag}/{audio_file}"
    ET.SubElement(item, "enclosure", {"url": media_url, "length": str(size), "type": "audio/mpeg"})

    dur_elem = ET.SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}duration")
    dur_elem.text = str(dur)

    channel.insert(
        list(channel).index(channel.find("item")) if channel.find("item") is not None else len(list(channel)), item)
    tree.write(FEED_FILE, encoding="utf-8", xml_declaration=True)
    return True


if __name__ == "__main__":
    vid = get_latest_stream_id()
    tag = f"ep-{datetime.date.today().strftime('%Y%m%d')}"
    mp3, ep_title, ep_size, ep_dur = process_audio(vid)
    updated = update_feed(mp3, ep_title, ep_size, ep_dur, tag)
    print(f"OUTPUT_TAG={tag}")
    print(f"OUTPUT_FILE={mp3}")