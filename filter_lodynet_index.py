import json, sys

with open('lodynet_turkish_index.json', encoding='utf-8') as f:
    data = json.load(f)

# Keep only real drama pages: title must contain both "مسلسل" and "مترجم"
# This removes nav items like songs, anime, film categories, etc.
clean = [
    entry for entry in data
    if 'مسلسل' in entry['title'] and 'مترجم' in entry['title']
]

with open('lodynet_turkish_dramas_clean.json', 'w', encoding='utf-8') as f:
    json.dump(clean, f, ensure_ascii=False, indent=2)

print(f"Total entries in raw file: {len(data)}")
print(f"Clean Turkish drama entries: {len(clean)}")
print(f"Removed (nav junk): {len(data) - len(clean)}")
print("Saved to: lodynet_turkish_dramas_clean.json")