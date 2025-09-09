Outil: mux_multi.py

But: Batch-muxer une source VOSTFR (vidéo + VO japonaise + sous-titres + polices) avec uniquement la piste audio FR extraite d'une source VF, afin de produire des MKV MULTi, sans ré-encoder la vidéo ni les sous-titres.

Prérequis
- OS: Linux, macOS ou Windows
- Python 3.8+
- ffmpeg et ffprobe accessibles dans le PATH (testés au lancement)
- Aucune dépendance externe (stdlib uniquement)
 
Installation rapide (selon l'OS)
- Windows (PowerShell):
  - Installer ffmpeg/ffprobe via winget:
    - winget install --id Gyan.FFmpeg -e --source winget
  - Important: ouvrez un NOUVEAU terminal après l'installation pour rafraîchir PATH.
- macOS:
  - brew install ffmpeg
- Debian/Ubuntu:
  - sudo apt update && sudo apt install -y ffmpeg
- Fedora:
  - sudo dnf install -y ffmpeg

Entrées CLI (obligatoires)
--vostfr-dir  Répertoire des fichiers VOSTFR (ex: MKV full).
--vf-dir      Répertoire des fichiers VF (peuvent être vidéo ou audio-only: mkv/mp4/mka/flac/aac/etc.).
--out-dir     Répertoire de sortie.

Options
--offsets-csv Fichier CSV "key,offset_ms" pour appliquer un décalage par épisode (ex: "E07,250" ou "E16,-120"). Positif = ajoute du silence au début; négatif = coupe le début. Le traitement ré-encode la piste VF en FLAC temporaire pour appliquer proprement l’offset.
--workers     Nombre de jobs en parallèle (par défaut: nombre de CPU).
--force       Écrase un fichier de sortie existant.
--dry-run     Affiche toutes les commandes ffmpeg exécutées sans rien écrire.
--no-speedfix Désactive la correction de vitesse PAL.

Appariement des épisodes
- Le script apparie VOSTFR et VF exclusivement via le motif EXX/EXXX (insensible à la casse) extrait par la regex stricte: \b[Ee](\d{2,3})\b.
- Tout fichier ne contenant pas ce motif est ignoré.
- Seuls les épisodes présents dans les deux dossiers sont traités.

Sélection des pistes
- VOSTFR: conserve
  - Vidéo
  - Audio VO (Japonais): détection par tags.language (jpn)
  - Sous-titres (ASS/SRT)
  - Attachments (polices)
- VF: extrait uniquement la piste audio FR (tags.language ∈ {fra, fre, fr}). Si aucune piste FR n’est trouvée, l’épisode est marqué en échec et ignoré.

Vitesse (PAL speedfix)
- Si VOSTFR ≈ 23.976 fps (24000/1001) et VF ≈ 25 fps (et que VF contient une vidéo permettant la détection), le script applique automatiquement atempo=0.95904 sur l’audio VF avant le mux.
- Cette étape se désactive avec --no-speedfix.
- Le speedfix et/ou l’offset entraînent un prétraitement audio VF en FLAC temporaire (supprimé après mux, sauf en dry-run).

Offsets CSV
- Format: "key,offset_ms" où key ∈ {E07, E16, E123} et offset_ms est un entier (peut être négatif).
- Exemple de fichier:
  E01,250
  E02,-120
  E10,0
- Décalage positif: ajoute du silence en tête.
- Décalage négatif: coupe le début de la piste.
- Le prétraitement produit une piste FLAC temporaire synchronisée avant le mux.

Tags et dispositions
- Audio 0: VO (Japonais) — language=jpn, title="VO (Japonais)", disposition=default.
- Audio 1: VF — language=fra, title="VF".
- Sous-titres FR (s’ils existent côté VOSTFR): marqués comme sous-titres par défaut.
- Les chapitres détectés côté VOSTFR sont préservés (map_chapters 0).
- Sortie: <nom_VOSTFR_sans_ext>.MULTi.mkv dans --out-dir.

Codecs
- Aucune ré-encodage vidéo ni sous-titres: -c:v copy, -c:s copy.
- L’audio VO est copié tel quel.
- L’audio VF est copié si non prétraité; sinon prétraité en FLAC (qualité sans perte).

Compatibilité
- Windows/macOS/Linux.
- Les chemins sont correctement quotés; --dry-run permet d’inspecter les commandes.
 
Guide d'utilisation
1) Vérification de l'installation
   - ffmpeg -version
   - ffprobe -version
2) Aide et options
   - python mux_multi.py --help
3) Exécution (exemples)
   - Windows:
     - python mux_multi.py --vostfr-dir "D:\Shows\VOSTFR" --vf-dir "D:\Shows\VF" --out-dir "D:\Shows\MULTI"
   - macOS/Linux:
     - python3 mux_multi.py --vostfr-dir "/mnt/data/VOSTFR" --vf-dir "/mnt/data/VF" --out-dir "/mnt/data/MULTI"
4) Dry-run (prévisualisation sans écrire):
   - python mux_multi.py --vostfr-dir "./vostfr" --vf-dir "./vf" --out-dir "./out" --dry-run
5) Offsets et parallélisme:
   - python mux_multi.py --vostfr-dir "/path/VOSTFR" --vf-dir "/path/VF" --out-dir "/path/MULTI" --offsets-csv offsets.csv --workers 4

Exemples
1) Exécution simple
   python mux_multi.py --vostfr-dir "D:\Shows\VOSTFR" --vf-dir "D:\Shows\VF" --out-dir "D:\Shows\MULTI"

2) Avec offsets et 4 workers
   python mux_multi.py --vostfr-dir "/mnt/data/VOSTFR" --vf-dir "/mnt/data/VF" --out-dir "/mnt/data/MULTI" --offsets-csv offsets.csv --workers 4

3) Dry-run (sans écrire)
   python mux_multi.py --vostfr-dir "./vostfr" --vf-dir "./vf" --out-dir "./out" --dry-run

Journalisation
- Pour chaque job, le script affiche:
  - Clé d’épisode (EXX)
  - Chemins VOSTFR/VF
  - Index de la piste FR choisie (VF)
  - Speedfix appliqué (oui/non)
  - Offset appliqué (ms)
  - Commandes ffmpeg (prétraitement et mux)

Codes de sortie
- 0: tous les épisodes traités avec succès.
- 1: au moins un épisode en échec.
- 2: ffmpeg/ffprobe manquants.

Remarques
- Le script se base sur les tags de langue; si les fichiers sont mal tagués, adaptez les sources ou corrigez les métadonnées.
- Le mapping par langage pour VO est strictement orienté vers 'jpn'; si aucune piste n’est taguée 'jpn', l’épisode est rejeté.
 
Notes pour dépôt GitHub public
- Licence: MIT (voir fichier LICENSE).
- Pas de clé API ni secret requis.
- Fichiers ignorés par défaut: voir .gitignore (cache Python, sorties .MULTi.mkv, dossiers temporaires, etc.).

Initialisation et publication du dépôt
1) Initialiser le dépôt git local:
   - git init
   - git add .
   - git commit -m "Initial commit: mux_multi tool, README, LICENSE, .gitignore"
2) Créer un dépôt GitHub vide (public) nommé, par ex., Muxage-MULTI.
3) Lier le dépôt local au dépôt distant et pousser:
   - git branch -M main
   - git remote add origin https://github.com/<votre-utilisateur>/Muxage-MULTI.git
   - git push -u origin main

Conseils
- Sous Windows après installation de ffmpeg via winget, ouvrez un nouveau terminal pour recharger PATH.
- Utilisez --dry-run pour valider les appariements et les commandes avant d’écrire quoi que ce soit.
