# Bot Telegram — Musique YouTube, Reels et vidéos sociales

Projet Python prêt à configurer. L'utilisateur écrit le titre d'une musique, idéalement suivi du nom de l'artiste, dans une conversation privée avec le bot. Celui-ci recherche sur YouTube, sélectionne automatiquement le premier résultat, télécharge l'audio, le convertit en MP3 et l'envoie dans le lecteur musical Telegram. Les liens YouTube directs sont aussi acceptés.

Le bot accepte également les liens publics de Reels et de vidéos Instagram, TikTok et Facebook. Il télécharge la vidéo et l'envoie en MP4 dans le lecteur Telegram, sans lien ni carte de plateforme dans sa réponse. Le choix est automatique : titre ou lien YouTube → MP3 ; lien Instagram, TikTok ou Facebook → MP4. La reconnaissance musicale à partir d'un enregistrement n'est pas intégrée.

Aucune étape de sélection n'est imposée à l'utilisateur. Un titre seul suffit, mais peut correspondre à plusieurs morceaux : préciser l'artiste, « version studio » ou « live » aide à orienter la recherche. Le premier résultat peut être une reprise ou un autre morceau ; son titre et son lien source sont affichés avec le MP3. Un lien direct permet de choisir exactement la vidéo. Le projet ne nécessite ni base de données, ni clé YouTube API.

## 1. Prérequis

- Python 3.11 ou plus récent : https://www.python.org/downloads/ . Sur Windows, cocher « Add Python to PATH » pendant l'installation.
- FFmpeg et FFprobe : https://ffmpeg.org/download.html . Depuis les liens Windows de cette page, récupérer une compilation, décompresser le dossier et ajouter son dossier `bin` au PATH Windows.
- Deno : suivre https://docs.deno.com/runtime/getting_started/installation/ . yt-dlp utilise ce moteur JavaScript pour la prise en charge de YouTube. Une installation compatible de Node.js peut aussi être utilisée.
- Une connexion Internet et un compte Telegram.

Rouvrir le terminal après installation et vérifier :

```powershell
py --version
ffmpeg -version
ffprobe -version
deno --version
```

Si FFmpeg n'est pas reconnu : dans Windows, chercher « variables d'environnement », ouvrir les variables utilisateur, modifier `Path`, ajouter le chemin du dossier contenant `ffmpeg.exe` et `ffprobe.exe`, puis rouvrir le terminal.

## 2. Créer le bot dans Telegram

1. Ouvrir le compte officiel [@BotFather](https://t.me/BotFather).
2. Envoyer `/newbot`.
3. Choisir un nom affiché, puis un identifiant disponible se terminant par `bot`.
4. Copier le token fourni. Il donne accès au bot : le garder dans `.env`, sans le publier ni l'envoyer dans une conversation.

## 3. Installer le projet sur Windows

Extraire l'archive ZIP. Ouvrir PowerShell **dans le dossier contenant `bot.py` et `requirements.txt`**, puis exécuter :

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Dans le Bloc-notes, remplacer `COLLER_ICI_LE_TOKEN_BOTFATHER` par le vrai token, enregistrer et fermer. Le fichier doit s'appeler exactement `.env`, pas `.env.txt`. La commande de copie ne doit être exécutée que lors de la première configuration, pour ne pas écraser un token déjà renseigné.

Lancer :

```powershell
.\.venv\Scripts\python.exe bot.py
```

Ces commandes utilisent directement le Python de l'environnement virtuel : aucune modification de la stratégie d'exécution PowerShell n'est nécessaire.

## 4. Utiliser le bot

Ouvrir le lien du bot fourni par BotFather et appuyer sur **Démarrer**. Envoyer `/start`, puis écrire le titre de la musique souhaitée, avec l'artiste si possible. Pour une vidéo précise, coller directement son lien YouTube. Choisir des contenus dont le téléchargement est autorisé.

Commandes disponibles :

| Commande | Action |
|---|---|
| `/start` ou `/aide` | Afficher les instructions |
| `/audio <titre et artiste>` | Chercher et recevoir le MP3 |
| `/audio <lien YouTube>` | Recevoir le MP3 de cette vidéo |
| `/video <lien Instagram, TikTok ou Facebook>` | Recevoir la vidéo en MP4 |
| Un titre seul | Recherche automatique, puis envoi du MP3 |
| `/id` | Afficher son identifiant Telegram numérique |
| Un lien YouTube seul | Même résultat que `/audio` |
| Un lien Instagram, TikTok ou Facebook seul | Même résultat que `/video` |

Les liens `youtube.com/watch`, `youtu.be`, `music.youtube.com` et `shorts` sont reconnus. Un lien vidéo comportant aussi un paramètre de playlist ne télécharge que la vidéo indiquée. Un lien de playlist seul est refusé.

Pour les vidéos sociales, les liens suivants sont reconnus :

| Plateforme | Formes de liens |
|---|---|
| Instagram | `/reel/…`, `/reels/…`, `/p/…`, `/tv/…` et partages `/share/reel/…` |
| TikTok | `/@utilisateur/video/…`, `vm.tiktok.com/…`, `vt.tiktok.com/…`, `/t/…` |
| Facebook | `/reel/…`, `/watch/?v=…`, `/utilisateur/videos/…`, `/share/r/…`, `/share/v/…`, `fb.watch/…` |

Envoyer un seul lien, sans texte autour. Les paramètres de suivi sont retirés. Les liens courts sont résolus uniquement vers les formes de liens vidéo autorisées de la même plateforme ; si la résolution échoue, le bot demande le lien direct. Les profils, albums/carrousels, playlists et directs sont refusés. `/audio` reste réservé à la musique YouTube ; `/video` est réservé aux trois plateformes sociales.

Les formats que yt-dlp signale comme portant un filigrane sont exclus. Si aucun format vidéo admissible n'est disponible, le bot explique l'échec. Cette sélection ne détecte pas les logos incrustés dans les pixels et ne les efface pas : l'absence de filigrane ne peut pas être garantie. Le bot n'ajoute aucun logo. L'aperçu éventuellement présent sur le message contenant le lien envoyé par l'utilisateur n'est pas modifié ; la réponse vidéo du bot ne cite pas ce message.

Le bot affiche « Recherche, téléchargement et conversion en cours… », puis « Envoi du MP3… ». Le fichier audio apparaît ensuite dans la conversation avec le titre et la source.

Le téléchargement depuis Telegram porte désormais le nom du morceau (`Titre de la chanson.mp3`). Les caractères interdits dans les noms de fichiers sont nettoyés, les accents sont conservés et les noms trop longs sont raccourcis.

Le titre, l'artiste et l'album lorsqu'il est fourni par YouTube sont enregistrés directement dans le MP3. La miniature YouTube est convertie en pochette JPEG intégrée aux tags ID3v2.3 ; une miniature distincte est envoyée à Telegram. L'audio n'est pas réencodé lors de cette étape. Si aucune image exploitable n'est disponible, le MP3 reste envoyé et le bot affiche « pochette indisponible ».

Après une mise à jour du code, arrêter le bot avec Ctrl+C et le relancer. Pour bénéficier du nom et de la pochette, demander à nouveau les morceaux au bot : les fichiers déjà envoyés ou téléchargés ne sont pas modifiés. La pochette intégrée est destinée aux lecteurs qui affichent les illustrations des MP3 ; l'icône dans l'explorateur du PC dépend aussi de ses paramètres et de sa prise en charge des miniatures.

## 5. Paramètres et fonctionnement

Les valeurs par défaut figurent dans `core.py` : vidéo de 20 minutes maximum, MP3 de 49 millions d'octets maximum, source de 80 millions d'octets maximum, deux demandes simultanées et délai total de recherche et de traitement de 5 minutes. Le MP3 est encodé à 192 kbit/s ; la qualité reste dépendante de la source. Le transfert vers Telegram dispose de délais supplémentaires.

Les vidéos sociales sont également limitées à 20 minutes, 80 millions d'octets de source cumulée et 49 millions d'octets pour le MP4 final. Les pistes compatibles H.264/AAC sont conservées lorsque la taille le permet ; les autres vidéos sont converties ou compressées en H.264/AAC, avec conservation du format portrait/paysage. Les vidéos muettes sont acceptées. La taille et la durée finales sont vérifiées avant l'envoi ; un fichier qui reste trop volumineux est refusé. Le téléchargement vidéo utilise les mêmes places et le même délai global que les demandes musicales.

Une seule demande par utilisateur peut être en cours. Quand les deux places sont occupées, le bot invite à réessayer ; cette version n'a pas de file d'attente persistante. Les fichiers temporaires sont supprimés à la fin de chaque traitement, succès ou erreur. Un arrêt forcé de l'ordinateur peut laisser un dossier temporaire `telegram-media-*` à nettoyer.

Par défaut, le bot répond à tout utilisateur qui le contacte **en privé**. Pour limiter l'accès : obtenir les identifiants avec `/id`, les inscrire dans `.env`, puis redémarrer :

```dotenv
ALLOWED_USER_IDS=123456789,987654321
```

Laisser cette valeur vide ouvre l'accès à tous. Les commandes d'aide et `/id` restent disponibles pour obtenir les identifiants. Les groupes ne sont pas pris en charge dans cette version.

## 6. Disponibilité et limites

Le programme doit rester lancé sur un ordinateur allumé et connecté. Fermer le terminal, mettre le PC en veille ou couper Internet interrompt le service. Pour une disponibilité continue, installer le projet sur un serveur capable d'exécuter Python, FFmpeg et Deno, puis superviser le processus. L'hébergement n'est pas inclus. Une seule instance doit utiliser le même token avec ce mode de réception des messages.

Sur Linux, créer l'environnement avec `python3 -m venv .venv`, installer les dépendances avec `.venv/bin/python -m pip install -r requirements.txt`, copier `.env.example` vers `.env`, renseigner le token et lancer `.venv/bin/python bot.py`. Installer aussi FFmpeg/FFprobe et Deno pour la distribution utilisée.

Le bot ne garantit pas « toutes les musiques ». Les vidéos privées, supprimées, soumises à connexion, aux restrictions régionales, au paiement ou à une protection peuvent être inaccessibles. YouTube peut également bloquer les téléchargements depuis certaines connexions, notamment des serveurs. Aucun mécanisme de contournement de ces restrictions n'est fourni. Utiliser le bot pour ses propres créations, des œuvres libres ou des contenus avec autorisation de téléchargement.

Les mêmes limites d'accès s'appliquent à Instagram, TikTok et Facebook. Aucun compte de ces plateformes ni fichier de cookies personnel n'est utilisé. Une vidéo publique peut échouer si la plateforme exige une connexion ou change son fonctionnement. L'extra `curl-cffi` de yt-dlp est inclus dans les dépendances pour la compatibilité de ses requêtes avec les plateformes sociales. La présence d'un extracteur ne garantit pas que chaque lien fonctionne : voir les [sites pris en charge par yt-dlp](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md).

Telegram accepte actuellement les audios MP3/M4A jusqu'à 50 MB via l'API standard ; ce projet garde une marge à 49 Mo. Voir la [documentation Telegram](https://core.telegram.org/bots/api#sendaudio).

## 7. Dépannage

| Problème | Vérification |
|---|---|
| Token manquant ou invalide | Vérifier `.env` dans le dossier de `bot.py`, et le token reçu de BotFather |
| FFmpeg/FFprobe non trouvé | Vérifier les commandes `-version`, le PATH et rouvrir le terminal |
| Aucun lien YouTube ne fonctionne | Mettre yt-dlp à jour, vérifier Deno et essayer une autre vidéo publique autorisée ; un blocage YouTube peut persister |
| Erreur de conflit Telegram | Arrêter l'autre instance utilisant le même token |
| Bot silencieux | Utiliser sa conversation privée, envoyer `/start`, vérifier que le terminal tourne et qu'Internet fonctionne |
| Mauvais morceau reçu | Préciser le titre et l’artiste, ou envoyer le lien exact |
| Demande refusée par durée/taille | Choisir une vidéo plus courte |
| Le MP3 ne s'envoie pas | Vérifier Internet et les limites ; vérifier la conversation avant de relancer pour éviter un doublon |
| Un Reel ne se télécharge pas | Essayer son lien direct public ; les liens nécessitant une connexion et les albums sont refusés ; mettre yt-dlp à jour |
| Un logo reste visible | Il peut être incrusté dans la vidéo ou ne pas être signalé par la plateforme ; le bot ne retouche pas l'image |
| Vidéo trop volumineuse | La compression est automatique, mais reste limitée ; essayer une vidéo plus courte |

Mise à jour de yt-dlp sur Windows, après arrêt du bot avec Ctrl+C :

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade "yt-dlp[default,curl-cffi]"
```

Si la version stable échoue à cause d'un changement récent de YouTube, le projet yt-dlp recommande aussi sa version nightly :

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade --pre "yt-dlp[default,curl-cffi]"
```

## 8. Structure et vérification

- `bot.py` : messages Telegram, contrôle d'accès, concurrence et envoi du fichier.
- `worker.py` : recherche YouTube, téléchargement, conversion, tags MP3 et pochettes dans un processus distinct.
- `reels.py` : liens de partage, sélection des formats vidéo, téléchargement social et préparation des MP4.
- `core.py` : validation des titres et des liens, noms de fichiers portables, limites.
- `.env.example` : modèle de configuration.
- `tests/` : tests locaux sans téléchargement réseau, dont vérification de vrais MP3 et pochettes avec FFmpeg/FFprobe (ces tests sont ignorés si les binaires manquent).

Exécuter les tests depuis le dossier du projet :

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Les tests locaux ne remplacent pas un essai avec ton token et une vidéo autorisée. Aucun bot Telegram n'a été enregistré ou activé automatiquement lors de la création de ce projet.

Références techniques : [Telegram BotFather](https://core.telegram.org/bots/tutorial#obtain-your-bot-token), [python-telegram-bot](https://docs.python-telegram-bot.org/), [yt-dlp et ses dépendances](https://github.com/yt-dlp/yt-dlp#dependencies).

Pochettes : [tags ID3 et images intégrées dans les MP3 avec FFmpeg](https://ffmpeg.org/ffmpeg-formats.html#mp3), [miniatures audio de l'API Telegram](https://core.telegram.org/bots/api#sendaudio).

Les tests vérifient les fonctions musicales, le routage audio/vidéo, les liens sociaux et leurs redirections, l'exclusion des formats signalés avec filigrane, les refus d'albums, la conversion de vraies vidéos avec ou sans son, la lecture progressive des MP4, les limites et le nettoyage des fichiers. Les services externes et l'envoi Telegram sont simulés ; une vidéo locale permet aussi de vérifier le parcours réel yt-dlp → FFmpeg. Un essai sur la connexion de déploiement reste nécessaire pour vérifier l'accès aux plateformes et l'affichage sur les appareils.
