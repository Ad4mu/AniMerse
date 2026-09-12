import subliminal
from babelfish import Language
from subliminal.video import Episode

video = Episode('Naruto', 'Naruto', 1, 5)
subtitles = subliminal.download_best_subtitles([video], {Language('spa')})
print(subtitles)

if subtitles[video]:
    subliminal.save_subtitles(video, subtitles[video])
    print("Saved")
