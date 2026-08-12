const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = {
  view: "library",
  page: 1,
  pages: 0,
  total: 0,
  sort: "recently_watched",
  direction: "desc",
  pageSize: (() => { try { const value = Number(localStorage.getItem("watchtracker-page-size")); return [24, 48, 96].includes(value) ? value : 24; } catch (_) { return 24; } })(),
  layout: (() => { try { return localStorage.getItem("watchtracker-layout") || "grid"; } catch (_) { return "grid"; } })(),
  filters: {},
  selectedResult: null,
  currentEntry: null,
  searchController: null,
  metadataSearchController: null,
  ratingReviewMode: false,
  searchTimer: null,
  enrichmentTimer: null,
  enrichmentStatus: "idle",
  generalSettingsSnapshot: null,
  migration: {sha256: null, summary: null},
  appearanceSave: Promise.resolve(),
  interfaceLanguage: "en",
  libraryLoaded: false,
  libraryLoading: false,
  libraryRequestId: 0
};

const navigationFilters = ["q", "media_type", "status", "genre", "year_min", "year_max", "rating_min", "rating_max", "rated", "include_deleted"];
const validSorts = new Set(["recently_watched", "recently_added", "personal_rating", "title", "release_year", "media_type"]);

const frenchText = {
  "Library": "Bibliothèque",
  "Insights": "Analyses",
  "Your library": "Votre bibliothèque",
  "Your viewing patterns": "Vos habitudes de visionnage",
  "Add to your library": "Ajouter à votre bibliothèque",
  "Search titles": "Rechercher des titres",
  "Search for a movie, show, or anime…": "Rechercher un film, une série ou un anime…",
  "Media type": "Type de média",
  "All types": "Tous les types",
  "Movies": "Films",
  "Movie": "Film",
  "TV": "Télévision",
  "TV series": "Série télévisée",
  "Anime": "Anime",
  "Library titles": "Titres dans la bibliothèque",
  "Completed": "Terminés",
  "Total viewings": "Visionnages totaux",
  "Average rating": "Note moyenne",
  "Rated titles": "Titres notés",
  "Rewatch rate": "Taux de revisionnage",
  "Library & your ratings": "Bibliothèque et vos notes",
  "Visual library breakdown": "Répartition visuelle de la bibliothèque",
  "Your watch profile": "Votre profil média",
  "Interactive explorer": "Explorateur interactif",
  "What shapes your taste?": "Qu’est-ce qui façonne vos goûts ?",
  "Dimension": "Dimension",
  "Measure": "Mesure",
  "Genres": "Genres",
  "Subgenres": "Sous-genres",
  "Provider tags": "Étiquettes du fournisseur",
  "Weighted share": "Part pondérée",
  "Average rating": "Note moyenne",
  "Title count": "Nombre de titres",
  "Personal ratings": "Notes personnelles",
  "Your rating curve": "Votre courbe de notes",
  "Status snapshot": "Aperçu des statuts",
  "Where your library stands": "État de votre bibliothèque",
  "Watch activity": "Activité de visionnage",
  "When you watched": "Quand vous avez regardé",
  "Watch outcomes": "Résultats de visionnage",
  "Completion and rewatches": "Achèvement et revisionnages",
  "Insight readiness": "Qualité des analyses",
  "How much evidence can insights use?": "Combien de données les analyses peuvent-elles utiliser ?",
  "Refresh": "Actualiser",
  "Settings": "Paramètres",
  "General": "Général",
  "Appearance": "Apparence",
  "Metadata": "Métadonnées",
  "Data & Backup": "Données et sauvegardes",
  "Privacy": "Confidentialité",
  "Shortcuts": "Raccourcis",
  "About": "À propos",
  "Timezone": "Fuseau horaire",
  "Metadata language": "Langue des métadonnées",
  "Metadata region": "Région des métadonnées",
  "Interface language": "Langue de l’interface",
  "English": "Anglais",
  "French": "Français",
  "United States": "États-Unis",
  "Save general settings": "Enregistrer les paramètres généraux",
  "Reset changes": "Annuler les modifications",
  "No unsaved changes": "Aucune modification non enregistrée",
  "Colour theme": "Thème de couleurs",
  "System": "Système",
  "Light": "Clair",
  "Dark": "Sombre",
  "Accent colour": "Couleur d’accentuation",
  "Forest": "Forêt",
  "Ocean": "Océan",
  "Violet": "Violet",
  "Rose": "Rose",
  "Amber": "Ambre",
  "Graphite": "Graphite",
  "Custom": "Personnalisée",
  "Background colour": "Couleur d’arrière-plan",
  "Colour strength": "Intensité de la couleur",
  "Background mode": "Mode d’arrière-plan",
  "Adaptive tint": "Teinte adaptative",
  "Full colour · ignore light/dark": "Couleur complète · ignorer clair/sombre",
  "Media artwork tint": "Teinte inspirée de l’affiche",
  "Let each Library card echo the colours of its own artwork.": "Laissez chaque fiche de la bibliothèque reprendre les couleurs de sa propre affiche.",
  "Media artwork tint help": "Aide sur la teinte inspirée de l’affiche",
  "Adds a subtle, readable colour atmosphere to each Library card using its poster artwork, with a title-based colour when no poster is available.": "Ajoute à chaque fiche une ambiance colorée subtile et lisible inspirée de son affiche, ou du titre lorsqu’aucune affiche n’est disponible.",
  "Use default": "Valeur par défaut",
  "Library layout": "Disposition de la bibliothèque",
  "Grid": "Grille",
  "List": "Liste",
  "TMDb read-access token": "Jeton d’accès en lecture TMDb",
  "Show while typing": "Afficher pendant la saisie",
  "Store this credential": "Stocker cet identifiant",
  "Local configuration file": "Fichier de configuration local",
  "Operating-system credential vault": "Coffre d’identifiants du système",
  "Save token": "Enregistrer le jeton",
  "Clear active token": "Effacer le jeton actif",
  "Library metadata": "Métadonnées de la bibliothèque",
  "Review unresolved": "Vérifier les éléments non résolus",
  "Refresh verified": "Actualiser les éléments vérifiés",
  "Review ratings": "Vérifier les notes",
  "Data & Backup": "Données et sauvegardes",
  "Local data": "Données locales",
  "Database size": "Taille de la base de données",
  "Last backup": "Dernière sauvegarde",
  "Never": "Jamais",
  "Create backup": "Créer une sauvegarde",
  "Open backups folder": "Ouvrir le dossier des sauvegardes",
  "Open data folder": "Ouvrir le dossier des données",
  "Open logs folder": "Ouvrir le dossier des journaux",
  "Keyboard shortcuts": "Raccourcis clavier",
  "Check for updates": "Rechercher des mises à jour",
  "GitHub repository": "Dépôt GitHub",
  "Close": "Fermer",
  "Open": "Ouvrir",
  "Import": "Importer",
  "Export": "Exporter",
  "Sort by": "Trier par",
  "Show": "Afficher",
  "Last watched date": "Date du dernier visionnage",
  "Date added to library": "Date d’ajout à la bibliothèque",
  "Personal rating": "Note personnelle",
  "Title": "Titre",
  "Release year": "Année de sortie",
  "Filter library": "Filtrer la bibliothèque",
  "Apply filters": "Appliquer les filtres",
  "Clear": "Effacer",
  "Watched": "Vu",
  "Watching": "En cours",
  "Plan to watch": "À regarder",
  "Dropped": "Abandonné",
  "Rewatching": "Revisionnage",
  "Details": "Détails",
  "Notes & tags": "Notes et étiquettes",
  "History": "Historique",
  "Save changes": "Enregistrer les modifications",
  "Add manually": "Ajouter manuellement",
  "Import watch history": "Importer l’historique",
  "Preview": "Aperçu",
  "Private and local-first. Your media history stays on this device.": "Privé et local. Votre historique multimédia reste sur cet appareil.",
  "Skip to content": "Aller au contenu",
  "Skip to library": "Aller à la bibliothèque",
  "Everything archive": "Archive complète",
  "Watch log CSV": "Journal de visionnage CSV",
  "Profile JSON": "Profil JSON",
  "Profile Markdown": "Profil Markdown",
  "Newest first": "Plus récents d’abord",
  "Oldest first": "Plus anciens d’abord",
  "Highest first": "Plus élevées d’abord",
  "Lowest first": "Plus faibles d’abord",
  "Find title": "Rechercher un titre",
  "All": "Tous",
  "Rated": "Notés",
  "Unrated": "Non notés",
  "Include deleted": "Inclure les éléments supprimés",
  "Genre or subgenre": "Genre ou sous-genre",
  "Release year from": "Année de sortie minimale",
  "Release year to": "Année de sortie maximale",
  "Rating from": "Note minimale",
  "Rating to": "Note maximale",
  "Rating state": "État de la note",
  "Ratings use only your personal scores. Activity charts use stored viewing dates and clearly separate undated imported view counts.": "Les notes utilisent uniquement vos évaluations personnelles. Les graphiques d’activité utilisent les dates enregistrées et distinguent les visionnages importés sans date.",
  "Search metadata providers or add a title yourself.": "Recherchez auprès des fournisseurs de métadonnées ou ajoutez vous-même un titre.",
  "Optional personal details": "Détails personnels facultatifs",
  "Watched date": "Date de visionnage",
  "Started date": "Date de début",
  "Finished date": "Date de fin",
  "View count": "Nombre de visionnages",
  "Tags": "Étiquettes",
  "Notes": "Notes",
  "Entry details": "Détails du titre",
  "Save rating & next": "Enregistrer la note et passer au suivant",
  "Started": "Commencé",
  "Finished": "Terminé",
  "Primary watched date": "Date principale de visionnage",
  "These overrides stay separate from provider metadata, so future refreshes will not erase them.": "Ces modifications restent séparées des métadonnées du fournisseur et ne seront pas effacées lors d’une actualisation.",
  "Genre additions": "Genres ajoutés",
  "Genre removals": "Genres retirés",
  "Subgenre additions": "Sous-genres ajoutés",
  "Subgenre removals": "Sous-genres retirés",
  "Catalog metadata": "Métadonnées du catalogue",
  "Search title": "Rechercher le titre",
  "All / not sure": "Tous / incertain",
  "Search providers": "Rechercher auprès des fournisseurs",
  "Next unresolved": "Élément non résolu suivant",
  "Viewing history": "Historique de visionnage",
  "More actions": "Plus d’actions",
  "Delete entry": "Supprimer le titre",
  "Restore entry": "Restaurer le titre",
  "Add a title manually": "Ajouter un titre manuellement",
  "Year": "Année",
  "Provider genres": "Genres du fournisseur",
  "Add to library": "Ajouter à la bibliothèque",
  "Cancel": "Annuler",
  "Preview a manual/canonical CSV or a Letterboxd export ZIP before anything changes.": "Prévisualisez un CSV manuel ou canonique, ou une archive Letterboxd, avant toute modification.",
  "File": "Fichier",
  "Format": "Format",
  "Detect automatically": "Détecter automatiquement",
  "Letterboxd ZIP": "Archive ZIP Letterboxd",
  "Personal-data conflicts": "Conflits de données personnelles",
  "Choose when required": "Choisir si nécessaire",
  "Preserve existing edits": "Conserver les modifications existantes",
  "Use imported values": "Utiliser les valeurs importées",
  "Import valid rows when invalid rows exist": "Importer les lignes valides même si certaines lignes sont invalides",
  "Refresh metadata for entries that already have a verified provider ID": "Actualiser les métadonnées des titres ayant déjà un identifiant fournisseur vérifié",
  "Commit import": "Confirmer l’importation",
  "Private · local-first.": "Privé · local en priorité.",
  "Your library and credentials stay on this device unless you export them.": "Votre bibliothèque et vos identifiants restent sur cet appareil sauf si vous les exportez.",
  "English (United States)": "Anglais (États-Unis)",
  "English (United Kingdom)": "Anglais (Royaume-Uni)",
  "German": "Allemand",
  "Spanish": "Espagnol",
  "Chinese (Simplified)": "Chinois (simplifié)",
  "Japanese": "Japonais",
  "Korean": "Coréen",
  "United Kingdom": "Royaume-Uni",
  "Canada": "Canada",
  "Australia": "Australie",
  "France": "France",
  "Germany": "Allemagne",
  "Spain": "Espagne",
  "China": "Chine",
  "Japan": "Japon",
  "South Korea": "Corée du Sud",
  "Unsaved changes": "Modifications non enregistrées",
  "Saved": "Enregistré",
  "Effective timezone": "Fuseau horaire actif",
  "Saving general settings…": "Enregistrement des paramètres généraux…",
  "General settings saved and verified.": "Paramètres généraux enregistrés et vérifiés.",
  "Choose a theme independently of your system preference.": "Choisissez un thème indépendamment des préférences du système.",
  "Presets adapt to light and dark themes. A custom colour is adjusted when needed to keep controls readable.": "Les préréglages s’adaptent aux thèmes clair et sombre. Une couleur personnalisée est ajustée si nécessaire pour préserver la lisibilité.",
  "Choose the colour, strength, and whether it should adapt to or replace light/dark surfaces.": "Choisissez la couleur, son intensité et si elle doit s’adapter aux surfaces claires ou sombres, ou les remplacer.",
  "Grid is visual; list keeps inline editing close at hand.": "La grille est visuelle ; la liste facilite la modification directe.",
  "Appearance changes save automatically.": "Les modifications d’apparence sont enregistrées automatiquement.",
  "Optional, and needed for movie and TV search. Use a TMDb API read-access token.": "Facultatif, mais nécessaire pour rechercher des films et séries. Utilisez un jeton d’accès en lecture de l’API TMDb.",
  "Easiest": "Le plus simple",
  "Unencrypted on disk with user-only permissions where supported. No operating-system password prompt.": "Non chiffré sur le disque, avec des autorisations réservées à l’utilisateur lorsque possible. Aucune demande de mot de passe du système.",
  "Maximum available protection. May request authentication and may be unavailable on some Linux distributions.": "Protection maximale disponible. Peut demander une authentification et ne pas être disponible sur certaines distributions Linux.",
  "Copy existing system-vault token locally": "Copier localement le jeton existant du coffre système",
  "Migrate legacy token": "Migrer l’ancien jeton",
  "Verified provider IDs can be refreshed automatically. Title-only records are never guessed.": "Les identifiants fournisseur vérifiés peuvent être actualisés automatiquement. Les titres seuls ne sont jamais associés au hasard.",
  "Ratings may be whole numbers or use one decimal. Review is an optional queue for revisiting existing scores; it does not require extra precision.": "Les notes peuvent être entières ou comporter une décimale. La révision est une file facultative et n’exige pas de précision supplémentaire.",
  "No key is required, but public releases keep this integration off by default to respect AniList's tracker-app restrictions.": "Aucune clé n’est requise, mais les versions publiques désactivent cette intégration par défaut afin de respecter les restrictions d’AniList.",
  "Anime fallback; no key required.": "Solution de secours pour les anime ; aucune clé requise.",
  "Checking…": "Vérification…",
  "Ready": "Prêt",
  "Flexible import": "Importation flexible",
  "Bring in almost any existing media list": "Importez presque toute liste multimédia existante",
  "Copyable conversion prompt": "Invite de conversion à copier",
  "Copy prompt": "Copier l’invite",
  "Open CSV / Letterboxd import": "Ouvrir l’importation CSV / Letterboxd",
  "Exact app-to-app transfer": "Transfert exact d’une application à l’autre",
  "Move another Personal Media Tracker library": "Transférer une autre bibliothèque Personal Media Tracker",
  "Export everything": "Tout exporter",
  "Tracker archive or database": "Archive ou base de données du tracker",
  "Inspect migration file": "Inspecter le fichier de migration",
  "Ready to import": "Prêt à importer",
  "Verified": "Vérifié",
  "Active titles": "Titres actifs",
  "Viewing events": "Événements de visionnage",
  "Deleted titles": "Titres supprimés",
  "Preferences": "Préférences",
  "Import this verified library": "Importer cette bibliothèque vérifiée",
  "Restore a backup": "Restaurer une sauvegarde",
  "Validate & restore": "Valider et restaurer",
  "Legacy database fallback": "Solution de secours pour une ancienne base",
  "Import database": "Importer la base de données",
  "Read the complete privacy notice": "Lire l’avis de confidentialité complet",
  "Open Add Media without leaving your current page": "Ouvrir Ajouter un média sans quitter la page actuelle",
  "Open Library and return to the top": "Ouvrir la bibliothèque et revenir en haut",
  "Open Insights and return to the top": "Ouvrir les analyses et revenir en haut",
  "Open Settings": "Ouvrir les paramètres",
  "Previous or next Library page": "Page précédente ou suivante de la bibliothèque",
  "Close the open dialog": "Fermer la fenêtre ouverte",
  "About Personal Media Tracker": "À propos de Personal Media Tracker",
  "Version": "Version",
  "Metadata attribution": "Attribution des métadonnées",
  "Released under the MIT License.": "Publié sous licence MIT.",
  "Welcome": "Bienvenue",
  "Your private media diary": "Votre journal multimédia privé",
  "Get started": "Commencer",
  "Optional metadata": "Métadonnées facultatives",
  "Set up movie & TV search": "Configurer la recherche de films et séries",
  "Save & continue": "Enregistrer et continuer",
  "Skip for now": "Ignorer pour l’instant",
  "How to get a TMDb read-access token": "Comment obtenir un jeton d’accès en lecture TMDb",
  "How would you like to begin?": "Comment souhaitez-vous commencer ?",
  "Search for a title": "Rechercher un titre",
  "Confirm action": "Confirmer l’action",
  "Confirm": "Confirmer",
  "Configured": "Configuré",
  "Not configured": "Non configuré",
  "Enabled by developer": "Activé par le développeur",
  "Disabled by policy": "Désactivé par la politique",
  "Environment override": "Priorité à la variable d’environnement",
  "Legacy .env compatibility": "Compatibilité avec l’ancien fichier .env",
  "No credential stored": "Aucun identifiant enregistré",
  "System local timezone": "Fuseau horaire local du système",
  "Needs more data": "Données supplémentaires requises",
  "Low": "Faible",
  "Medium": "Moyenne",
  "High": "Élevée",
  "Undated": "Sans date",
  "Year unknown": "Année inconnue",
  "Updated": "Mis à jour",
  "Calculating insights…": "Calcul des analyses…",
  "Personal rating distribution": "Répartition des notes personnelles",
  "Rate completed titles to reveal your distribution.": "Notez des titres terminés pour afficher votre répartition.",
  "titles": "titres",
  "completion": "terminés",
  "completed but unrated": "terminés mais non notés",
  "metadata verified": "métadonnées vérifiées",
  "median": "médiane",
  "rated titles": "titres notés",
  "total titles": "titres au total",
  "dated this year": "datés cette année",
  "undated, kept out of timeline": "sans date, exclus de la chronologie",
  "Recent months": "Mois récents",
  "Days of the week": "Jours de la semaine",
  "Only stored viewing dates appear here. Imported view counts without dates remain in your totals and are shown separately rather than guessed.": "Seules les dates de visionnage enregistrées apparaissent ici. Les visionnages importés sans date restent dans vos totaux et sont affichés séparément au lieu d’être estimés.",
  "completed": "terminés",
  "rewatched": "revisionnés",
  "completed titles rated": "titres terminés notés",
  "More personal ratings strengthen taste confidence. Verified provider matches add genres and tags without guessing.": "Davantage de notes personnelles renforcent la fiabilité de vos goûts. Les correspondances vérifiées ajoutent des genres et des étiquettes sans supposition.",
  "Formats, origins & length": "Formats, origines et durée",
  "Secondary provider attributes, minimized until you need them": "Attributs secondaires du fournisseur, réduits jusqu’à ce que vous en ayez besoin",
  "Formats": "Formats",
  "Countries": "Pays",
  "Languages": "Langues",
  "Runtime patterns": "Tendances de durée",
  "Episode-count patterns": "Tendances du nombre d’épisodes",
  "Titles & detailed signals": "Titres et signaux détaillés",
  "Top titles, rewatches, positive and negative signals": "Meilleurs titres, revisionnages et signaux positifs ou négatifs",
  "Top titles": "Meilleurs titres",
  "Most rewatched": "Les plus revisionnés",
  "Positive signals": "Signaux positifs",
  "Negative signals": "Signaux négatifs",
  "Taste evidence": "Indices de préférence",
  "Provider tag signals": "Signaux des étiquettes fournisseur",
  "Data quality & confidence": "Qualité des données et fiabilité",
  "Coverage, scoring definitions, and exactly how to improve confidence": "Couverture, définitions des scores et moyens précis d’améliorer la fiabilité",
  "How confidence works": "Fonctionnement de la fiabilité",
  "For affinity rows, confidence is based on titles that both carry that signal and have a personal rating:": "Pour les affinités, la fiabilité repose sur les titres qui possèdent ce signal et une note personnelle :",
  "Rate more titles with the same verified genre or provider tag to increase it.": "Notez davantage de titres ayant le même genre vérifié ou la même étiquette fournisseur pour l’augmenter.",
  "Weighted share is different from confidence.": "La part pondérée est différente de la fiabilité.",
  "It is that signal's share of all rating-weighted signals, after each title splits its weight across its tags. A broad library can therefore produce high confidence but a very small percentage. Small non-zero values display with decimals instead of rounding to 0%.": "Il s’agit de la part de ce signal parmi tous les signaux pondérés par les notes, après répartition du poids de chaque titre entre ses étiquettes. Une grande bibliothèque peut donc produire une fiabilité élevée mais un faible pourcentage. Les petites valeurs non nulles conservent leurs décimales au lieu d’être arrondies à 0 %.",
  "Metadata coverage": "Couverture des métadonnées",
  "Genre affinity": "Affinité par genre",
  "Subgenre affinity": "Affinité par sous-genre",
  "Value": "Valeur",
  "Titles": "Titres",
  "Share": "Part",
  "Avg rating": "Note moy.",
  "Confidence": "Fiabilité",
  "Signal": "Signal",
  "Scope": "Portée",
  "Type": "Type",
  "Rating": "Note",
  "Views": "Visionnages",
  "Evidence": "Indice",
  "Examples": "Exemples",
  "Field": "Champ",
  "Known": "Connus",
  "Eligible": "Éligibles",
  "Coverage": "Couverture",
  "Not enough matching data yet.": "Pas encore assez de données correspondantes.",
  "Not enough data yet.": "Pas encore assez de données.",
  "Select a bar to inspect its evidence.": "Sélectionnez une barre pour examiner ses données.",
  "Share of all rating-weighted signals. Bars are scaled against the strongest result so small signals stay visible.": "Part de tous les signaux pondérés par les notes. Les barres sont comparées au résultat le plus fort afin que les petits signaux restent visibles.",
  "Mean personal rating among rated titles carrying each signal.": "Note personnelle moyenne parmi les titres notés portant chaque signal.",
  "Completed titles carrying each signal.": "Titres terminés portant chaque signal.",
  "Not enough matching metadata and ratings yet.": "Pas encore assez de métadonnées et de notes correspondantes.",
  "Add watched dates to reveal monthly activity.": "Ajoutez des dates de visionnage pour afficher l’activité mensuelle.",
  "Add ratings to turn your library into a personal taste profile.": "Ajoutez des notes pour transformer votre bibliothèque en profil de goûts personnel.",
  "insufficient data": "données insuffisantes",
  "highly selective, strongly positive ratings": "notes très sélectives et fortement positives",
  "generally positive ratings": "notes généralement positives",
  "balanced ratings": "notes équilibrées",
  "critical ratings": "notes critiques",
  "Verified provider identity": "Identité fournisseur vérifiée",
  "Poster": "Affiche",
  "Provider genres": "Genres du fournisseur",
  "Provider tags": "Étiquettes du fournisseur",
  "Format": "Format",
  "Country": "Pays",
  "Language": "Langue",
  "Runtime": "Durée",
  "Episode count": "Nombre d’épisodes",
  "movies": "films",
  "TV / anime episodes": "épisodes TV / anime",
  "TV / anime": "TV / anime",
  "Under 90 min": "Moins de 90 min",
  "Under 25 min": "Moins de 25 min",
  "1–6 episodes": "1 à 6 épisodes",
  "7–13 episodes": "7 à 13 épisodes",
  "14–26 episodes": "14 à 26 épisodes",
  "27–52 episodes": "27 à 52 épisodes",
  "53+ episodes": "53 épisodes ou plus",
  "Media artwork tint saved automatically.": "Teinte inspirée de l’affiche enregistrée automatiquement.",
  "Media artwork tint turned off.": "Teinte inspirée de l’affiche désactivée.",
  "Personal Media Tracker home": "Accueil de Personal Media Tracker",
  "Quick add a title": "Ajouter rapidement un titre",
  "Quick add (⌘K or /)": "Ajout rapide (⌘K ou /)",
  "Toggle light or dark theme": "Basculer entre les thèmes clair et sombre",
  "Toggle colour theme": "Changer le thème de couleurs",
  "Toggle library filters": "Afficher ou masquer les filtres",
  "Reverse sort order": "Inverser l’ordre de tri",
  "Sort descending": "Tri décroissant",
  "Titles per page": "Titres par page",
  "Add rewatch today": "Ajouter un revisionnage aujourd’hui",
  "Status": "Statut",
  "Metadata media type": "Type de média des métadonnées",
  "Comma separated": "Séparés par des virgules",
  "Optional · 1–10": "Facultatif · 1–10",
  "Entry sections": "Sections du titre",
  "Title search results": "Résultats de la recherche de titres",
  "Settings sections": "Sections des paramètres",
  "Dismiss": "Fermer",
  "Dismiss privacy reminder": "Masquer le rappel de confidentialité",
  "Colour theme help": "Aide sur le thème de couleurs",
  "System follows your computer. Light and dark stay fixed until you change them.": "Le mode système suit votre ordinateur. Les modes clair et sombre restent fixes jusqu’à ce que vous les changiez.",
  "Accent colour help": "Aide sur la couleur d’accentuation",
  "Changes buttons, selected controls, links, and chart highlights. Choose a preset or use the colour picker.": "Modifie les boutons, les contrôles sélectionnés, les liens et les éléments mis en évidence dans les graphiques. Choisissez un préréglage ou utilisez le sélecteur de couleur.",
  "Custom accent colour": "Couleur d’accentuation personnalisée",
  "Forest accent": "Accent forêt",
  "Ocean accent": "Accent océan",
  "Violet accent": "Accent violet",
  "Rose accent": "Accent rose",
  "Amber accent": "Accent ambre",
  "Graphite accent": "Accent graphite",
  "Background colour help": "Aide sur la couleur d’arrière-plan",
  "Adaptive tint blends your colour with the selected light or dark theme. Full colour makes your choice the dominant interface colour and chooses readable text automatically.": "La teinte adaptative mélange votre couleur au thème clair ou sombre choisi. Le mode couleur complète en fait la couleur dominante de l’interface et choisit automatiquement un texte lisible.",
  "Custom background colour": "Couleur d’arrière-plan personnalisée",
  "Library layout help": "Aide sur la disposition de la bibliothèque",
  "Use the grid or list buttons on the Library page. This indicator shows the current choice.": "Utilisez les boutons grille ou liste de la page Bibliothèque. Cet indicateur affiche le choix actuel.",
  "Grid layout": "Disposition en grille",
  "List layout": "Disposition en liste",
  "Timezone help": "Aide sur le fuseau horaire",
  "Controls date boundaries, today labels, backup timestamps, and activity charts. The saved effective timezone is shown below.": "Contrôle les limites de dates, les mentions d’aujourd’hui, les horodatages des sauvegardes et les graphiques d’activité. Le fuseau horaire actif enregistré est affiché ci-dessous.",
  "Metadata language help": "Aide sur la langue des métadonnées",
  "Requests translated titles, summaries, and other text from metadata providers when available. It does not translate app menus.": "Demande aux fournisseurs des titres, résumés et autres textes traduits lorsqu’ils sont disponibles. Ce réglage ne traduit pas les menus de l’application.",
  "Metadata region help": "Aide sur la région des métadonnées",
  "Helps providers choose regional release dates and localized availability. It does not change where your data is stored.": "Aide les fournisseurs à choisir les dates de sortie régionales et les disponibilités locales. Ce réglage ne change pas l’emplacement de vos données.",
  "Interface language help": "Aide sur la langue de l’interface",
  "Changes application menus, buttons, headings, and common status text. It is separate from the metadata language.": "Modifie les menus, boutons, titres et libellés d’état courants. Ce réglage est distinct de la langue des métadonnées.",
  "Timezone is validated as an IANA name. Metadata locale settings change provider results. Environment variables still take priority for developer installs.": "Le fuseau horaire est validé comme nom IANA. Les réglages régionaux des métadonnées modifient les résultats des fournisseurs. Les variables d’environnement restent prioritaires pour les installations de développement.",
  "TMDb help": "Aide sur TMDb",
  "TMDb is optional but powers movie and TV search. Jikan anime search and manual entry still work without it; developers may enable AniList where authorized.": "TMDb est facultatif mais permet la recherche de films et séries. La recherche d’anime via Jikan et l’ajout manuel fonctionnent sans ce service ; les développeurs peuvent activer AniList lorsqu’ils y sont autorisés.",
  "TMDb token help": "Aide sur le jeton TMDb",
  "A credential created in your TMDb account. It is never displayed again or included in backups and exports.": "Identifiant créé dans votre compte TMDb. Il n’est jamais réaffiché ni inclus dans les sauvegardes et exportations.",
  "Optional. Enables movie and TV search, posters, summaries, genres, release dates, and related metadata.": "Facultatif. Active la recherche de films et séries, les affiches, résumés, genres, dates de sortie et métadonnées associées.",
  "Paste a new token": "Coller un nouveau jeton",
  "Credential storage help": "Aide sur le stockage de l’identifiant",
  "The local configuration file is easiest and avoids password prompts, but it is not encrypted. The system vault offers stronger protection when the operating system provides one.": "Le fichier de configuration local est le plus simple et évite les demandes de mot de passe, mais il n’est pas chiffré. Le coffre système offre une meilleure protection lorsque le système d’exploitation en propose un.",
  "Library metadata help": "Aide sur les métadonnées de la bibliothèque",
  "Refresh verified updates records already connected to a provider. Review unresolved lets you confirm matches title by title.": "Actualiser les éléments vérifiés met à jour les fiches déjà liées à un fournisseur. Vérifier les éléments non résolus vous permet de confirmer chaque correspondance.",
  "Personal ratings help": "Aide sur les notes personnelles",
  "Scores use a 1–10 scale. Decimals are optional; 8 and 8.0 mean the same thing.": "Les notes utilisent une échelle de 1 à 10. Les décimales sont facultatives ; 8 et 8,0 ont la même signification.",
  "AniList help": "Aide sur AniList",
  "No token is requested. The integration is intentionally unavailable in this public build because AniList restricts competing tracker apps.": "Aucun jeton n’est demandé. L’intégration est volontairement indisponible dans cette version publique, car AniList limite les applications de suivi concurrentes.",
  "Jikan help": "Aide sur Jikan",
  "Provides public MyAnimeList-derived anime search as a fallback. It does not require an account or API key.": "Fournit une recherche publique d’anime dérivée de MyAnimeList comme solution de secours. Aucun compte ni clé API n’est nécessaire.",
  "The app directly reads CSV and Letterboxd ZIP files. An optional AI-assisted step can normalize other lists into the supported CSV shape.": "L’application lit directement les fichiers CSV et les archives ZIP Letterboxd. Une étape facultative assistée par IA peut convertir d’autres listes au format CSV pris en charge.",
  "Flexible import help": "Aide sur l’importation flexible",
  "The app directly previews UTF-8 CSV files and Letterboxd export ZIPs. If your list is a document, spreadsheet, text file, JSON, or an unusual export, you can first convert a copy to the small CSV format below.": "L’application prévisualise directement les fichiers CSV UTF-8 et les archives d’exportation Letterboxd. Si votre liste est un document, une feuille de calcul, un fichier texte, du JSON ou un export inhabituel, convertissez d’abord une copie au petit format CSV ci-dessous.",
  "Decide whether your source contains ratings and identify its scale (for example, 5 stars, 10 points, or 100%).": "Déterminez si votre source contient des notes et identifiez leur échelle (par exemple 5 étoiles, 10 points ou 100 %).",
  "Optionally paste the prompt and a copy of your list into an AI model, or use the same column rules to format it yourself.": "Vous pouvez coller l’invite et une copie de votre liste dans un modèle d’IA, ou appliquer vous-même les mêmes règles de colonnes.",
  "Review the result, save it as a UTF-8": "Vérifiez le résultat et enregistrez-le comme fichier UTF-8",
  "file, then use": "puis utilisez",
  "to preview every change before committing.": "pour prévisualiser chaque modification avant de confirmer.",
  "An AI service is optional and separate from this app. Uploading a list shares it with that provider, so remove private notes or use an offline model if that matters to you. Always review generated CSV; the app will show a preview and will not change your library until you commit it.": "Un service d’IA est facultatif et distinct de cette application. L’envoi d’une liste la partage avec ce fournisseur : retirez donc vos notes privées ou utilisez un modèle hors ligne si cela vous importe. Vérifiez toujours le CSV produit ; l’application affiche un aperçu et ne modifie pas votre bibliothèque avant votre confirmation.",
  "Privacy note:": "Note de confidentialité :",
  "Tracker migration file help": "Aide sur le fichier de migration",
  "Choose an Everything archive from this app, or a watchtracker.sqlite3 database from an older installation that could not export one.": "Choisissez une archive complète de cette application, ou une base watchtracker.sqlite3 provenant d’une ancienne installation qui ne pouvait pas en exporter.",
  "Use this only for a Personal Media Tracker archive or a legacy Personal Watch Tracker database—not for a general media list. It preserves titles, ratings, statuses, notes, tags, viewing history, metadata, deleted items, and portable preferences. Credentials are excluded.": "Utilisez cette option uniquement pour une archive Personal Media Tracker ou une ancienne base Personal Watch Tracker, et non pour une liste multimédia générale. Elle conserve les titres, notes, statuts, commentaires, étiquettes, historiques, métadonnées, éléments supprimés et préférences transférables. Les identifiants sont exclus.",
  "Importing replaces the current library only after the selected file is verified again. A safety backup is created first.": "L’importation ne remplace la bibliothèque actuelle qu’après une nouvelle vérification du fichier choisi. Une sauvegarde de sécurité est d’abord créée.",
  "The current database is safety-backed up before a validated restore.": "La base actuelle est sauvegardée par sécurité avant toute restauration validée.",
  "Legacy database help": "Aide sur l’ancienne base de données",
  "For an older Personal Watch Tracker only. The selected database is validated and copied; the source file is never moved or deleted.": "Uniquement pour une ancienne installation de Personal Watch Tracker. La base choisie est validée et copiée ; le fichier source n’est jamais déplacé ni supprimé.",
  "If the older tracker cannot export a ZIP, select its": "Si l’ancien tracker ne peut pas exporter d’archive ZIP, choisissez son fichier",
  "file. The original is copied and never deleted.": "Le fichier d’origine est copié et n’est jamais supprimé.",
  "Your library, notes, ratings, imports, and backups stay on this computer unless you deliberately copy or export them.": "Votre bibliothèque, vos notes, vos évaluations, vos importations et vos sauvegardes restent sur cet ordinateur sauf si vous décidez de les copier ou de les exporter.",
  "Provider searches contact TMDb, AniList, or Jikan; poster loading contacts their image services. Manual update checks contact GitHub. Personal Media Tracker has no account, central server, telemetry, or behavioral analytics.": "Les recherches contactent TMDb, AniList ou Jikan, et le chargement des affiches contacte leurs services d’images. Les recherches manuelles de mises à jour contactent GitHub. Personal Media Tracker n’utilise ni compte, ni serveur central, ni télémétrie, ni analyse comportementale.",
  "Shortcuts are disabled while you are typing. Tab and arrow-key navigation continue to follow standard accessible controls.": "Les raccourcis sont désactivés pendant la saisie. La touche Tab et les flèches conservent le comportement accessible standard.",
  "This product uses the TMDB API but is not endorsed or certified by TMDB. Anime metadata may be provided by AniList and Jikan/MyAnimeList.": "Ce produit utilise l’API TMDB, mais n’est ni approuvé ni certifié par TMDB. Les métadonnées d’anime peuvent provenir d’AniList et de Jikan/MyAnimeList.",
  "Track movies, TV, limited series, and anime in a library that lives on this computer. There is no account, cloud database, or telemetry.": "Suivez films, séries, séries limitées et anime dans une bibliothèque conservée sur cet ordinateur. Aucun compte, aucune base infonuagique et aucune télémétrie ne sont utilisés.",
  "Automatic": "Automatique",
  "Library pages": "Pages de la bibliothèque",
  "Primary": "Navigation principale",
  "or": "ou",
  "＋ Add manually": "＋ Ajouter manuellement",
  "Saving appearance…": "Enregistrement de l’apparence…",
  "Saved on this device, but portable-backup sync is pending. Change the option once more to retry.": "Enregistré sur cet appareil, mais la synchronisation avec les sauvegardes transférables est en attente. Modifiez de nouveau l’option pour réessayer.",
  "Entry updated": "Titre mis à jour",
  "Changes saved": "Modifications enregistrées",
  "Metadata attached": "Métadonnées associées",
  "Rating saved": "Note enregistrée",
  "Manual title added": "Titre manuel ajouté",
  "Import complete": "Importation terminée",
  "Metadata settings saved": "Paramètres des métadonnées enregistrés",
  "Settings saved": "Paramètres enregistrés",
  "Backup created safely": "Sauvegarde créée en toute sécurité",
  "Existing database imported": "Base de données existante importée",
  "Backup restored": "Sauvegarde restaurée",
  "Complete library imported": "Bibliothèque complète importée",
  "Rewatch added today": "Revisionnage ajouté aujourd’hui",
  "Entry restored": "Titre restauré",
  "Conversion prompt copied": "Invite de conversion copiée",
  "Export saved": "Exportation enregistrée",
  "Export was not saved": "L’exportation n’a pas été enregistrée",
  "Export could not be saved. Your library was not changed.": "L’exportation n’a pas pu être enregistrée. Votre bibliothèque n’a pas été modifiée."
};
const localizedTextOriginals = new WeakMap();
const localizedFrenchOverrides = new WeakMap();
const localizedAttributeOriginals = new WeakMap();

function interfaceLanguagePreference() {
  try { return localStorage.getItem("watchtracker-interface-language") === "fr" ? "fr" : "en"; }
  catch (_) { return "en"; }
}

function translatedText(value) {
  return state.interfaceLanguage === "fr" ? (frenchText[value] || value) : value;
}

function interfaceLocale() {
  return state.interfaceLanguage === "fr" ? "fr-FR" : "en-US";
}

function formatInteger(value) {
  return Number(value || 0).toLocaleString(interfaceLocale(), {maximumFractionDigits: 0});
}

function countText(count, englishSingular, englishPlural, frenchSingular, frenchPlural) {
  const label = state.interfaceLanguage === "fr"
    ? (Number(count) === 1 ? frenchSingular : frenchPlural)
    : (Number(count) === 1 ? englishSingular : englishPlural);
  return `${formatInteger(count)} ${label}`;
}

function setLocalizedText(element, english, french = null) {
  element.textContent = english;
  const node = element.firstChild;
  if (!node) return;
  localizedTextOriginals.set(node, english);
  if (french) localizedFrenchOverrides.set(node, french);
  node.nodeValue = state.interfaceLanguage === "fr" ? (french || frenchText[english] || english) : english;
}

function localizeTree(root = document.body) {
  if (!root) return;
  const textNodes = [];
  if (root.nodeType === Node.TEXT_NODE) textNodes.push(root);
  else {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) textNodes.push(walker.currentNode);
  }
  textNodes.forEach(node => {
    if (node.parentElement?.closest("script, style, pre, code, [translate='no']")) return;
    if (!localizedTextOriginals.has(node)) localizedTextOriginals.set(node, node.nodeValue);
    const original = localizedTextOriginals.get(node);
    const trimmed = original.trim();
    if (!trimmed) return;
    const replacement = state.interfaceLanguage === "fr" ? (localizedFrenchOverrides.get(node) || frenchText[trimmed] || trimmed) : trimmed;
    node.nodeValue = original.replace(trimmed, replacement);
  });
  const elements = root.nodeType === Node.ELEMENT_NODE ? [root, ...root.querySelectorAll("*")] : [];
  elements.forEach(element => {
    if (element.closest("[translate='no']")) return;
    if (!localizedAttributeOriginals.has(element)) {
      localizedAttributeOriginals.set(element, Object.fromEntries(
        ["aria-label", "title", "placeholder", "data-tip"].filter(name => element.hasAttribute(name)).map(name => [name, element.getAttribute(name)])
      ));
    }
    Object.entries(localizedAttributeOriginals.get(element)).forEach(([name, original]) => {
      element.setAttribute(name, state.interfaceLanguage === "fr" ? (frenchText[original] || original) : original);
    });
  });
}

function applyInterfaceLanguage(language, {persist = true} = {}) {
  const selected = language === "fr" ? "fr" : "en";
  const changed = state.interfaceLanguage !== selected;
  state.interfaceLanguage = selected;
  if (persist) {
    try { localStorage.setItem("watchtracker-interface-language", selected); } catch (_) { /* optional */ }
  }
  document.documentElement.lang = selected;
  document.title = selected === "fr" ? "Personal Media Tracker · Bibliothèque" : "Personal Media Tracker";
  if ($("#interface-language")) $("#interface-language").value = selected;
  localizeTree(document.body);
  if ($("#sort-direction")) updateSortDirectionControl();
  if (changed && state.view === "insights" && $("#insights-content")?.childElementCount) {
    queueMicrotask(() => loadInsights());
  } else if (changed && state.view === "library" && state.libraryLoaded) {
    queueMicrotask(() => loadLibrary({showSkeleton: false}));
  }
}

function hideHelpTooltip() {
  const tooltip = $("#floating-help-tooltip");
  if (tooltip) tooltip.hidden = true;
}

function refreshHelpTooltipAfterScroll() {
  hideHelpTooltip();
  const trigger = $(".help-tip:hover") || (document.activeElement?.matches?.(".help-tip") ? document.activeElement : null);
  if (trigger) requestAnimationFrame(() => showHelpTooltip(trigger));
}

function showHelpTooltip(trigger) {
  let tooltip = $("#floating-help-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.id = "floating-help-tooltip";
    tooltip.className = "floating-help-tooltip";
    tooltip.role = "tooltip";
    tooltip.hidden = true;
    document.body.append(tooltip);
  }
  tooltip.textContent = trigger.dataset.tip || "";
  tooltip.hidden = false;
  const rect = trigger.getBoundingClientRect();
  const margin = 12;
  const preferredLeft = rect.left + rect.width / 2 - tooltip.offsetWidth / 2;
  tooltip.style.left = `${Math.max(margin, Math.min(preferredLeft, window.innerWidth - tooltip.offsetWidth - margin))}px`;
  const below = rect.bottom + 8;
  tooltip.style.top = `${below + tooltip.offsetHeight <= window.innerHeight - margin ? below : Math.max(margin, rect.top - tooltip.offsetHeight - 8)}px`;
}

function bindHelpTips(root = document) {
  if (!$("#floating-help-tooltip")) {
    const tooltip = document.createElement("div");
    tooltip.id = "floating-help-tooltip";
    tooltip.className = "floating-help-tooltip";
    tooltip.role = "tooltip";
    tooltip.hidden = true;
    document.body.append(tooltip);
  }
  $$(".help-tip", root).forEach(trigger => {
    if (trigger.dataset.tooltipBound) return;
    trigger.dataset.tooltipBound = "true";
    trigger.setAttribute("aria-describedby", "floating-help-tooltip");
    trigger.addEventListener("mouseenter", () => showHelpTooltip(trigger));
    trigger.addEventListener("mouseleave", hideHelpTooltip);
    trigger.addEventListener("focus", () => showHelpTooltip(trigger));
    trigger.addEventListener("blur", hideHelpTooltip);
  });
}

function restoreNavigationState() {
  const params = new URLSearchParams(window.location.search);
  state.view = params.get("view") === "insights" ? "insights" : "library";
  const page = Number(params.get("page"));
  state.page = Number.isInteger(page) && page > 0 ? page : 1;
  const sort = params.get("sort");
  state.sort = validSorts.has(sort) ? sort : "recently_watched";
  state.direction = params.get("direction") === "asc" ? "asc" : "desc";
  const pageSize = Number(params.get("page_size"));
  if ([24, 48, 96].includes(pageSize)) state.pageSize = pageSize;
  const layout = params.get("layout");
  if (layout === "grid" || layout === "list") state.layout = layout;
  state.filters = {};
  navigationFilters.forEach(key => {
    if (!params.has(key)) return;
    state.filters[key] = key === "include_deleted" ? params.get(key) === "true" : params.get(key);
  });
}

function persistNavigationState() {
  const params = new URLSearchParams({
    view: state.view,
    page: String(state.page),
    sort: state.sort,
    direction: state.direction,
    page_size: String(state.pageSize),
    layout: state.layout
  });
  Object.entries(state.filters).forEach(([key, value]) => {
    if (value !== "" && value !== false && value != null && !(key === "rated" && value === "all")) params.set(key, String(value));
  });
  const query = params.toString();
  history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`);
}

function applyNavigationControls() {
  $("#sort").value = state.sort;
  $("#page-size").value = String(state.pageSize);
  updateSortDirectionControl();
  const form = $("#filter-form");
  navigationFilters.forEach(key => {
    const control = form.elements.namedItem(key);
    if (!control) return;
    if (control.type === "checkbox") control.checked = Boolean(state.filters[key]);
    else control.value = state.filters[key] ?? (key === "rated" ? "all" : "");
  });
  updateFilterBadge();
}

function sortDirectionLabel() {
  const ascending = state.direction === "asc";
  if (state.sort === "title" || state.sort === "media_type") return ascending ? "A–Z" : "Z–A";
  if (state.sort === "personal_rating") return translatedText(ascending ? "Lowest first" : "Highest first");
  return translatedText(ascending ? "Oldest first" : "Newest first");
}

function updateSortDirectionControl() {
  const direction = $("#sort-direction");
  direction.firstElementChild.textContent = state.direction === "desc" ? "↓" : "↑";
  $("#sort-direction-label").textContent = sortDirectionLabel();
  direction.setAttribute("aria-label", state.interfaceLanguage === "fr" ? `Inverser l’ordre de tri. Ordre actuel : ${sortDirectionLabel()}` : `Reverse sort order. Current order: ${sortDirectionLabel()}`);
}

function esc(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
}
function safeImageUrl(value) {
  if (!value) return null;
  try {
    const parsed = new URL(value, window.location.origin);
    return parsed.protocol === "https:" || parsed.origin === window.location.origin ? parsed.href : null;
  } catch (_) { return null; }
}
function imageHtml(url, title, classes = "", alt = "") {
  const safe = safeImageUrl(url);
  return safe ? `<img class="${esc(classes)}" src="${esc(safe)}" alt="${esc(alt)}" loading="lazy" data-fallback-title="${esc(title)}">` : posterFallback(title, classes);
}
function listValue(value) { return String(value || "").split(/[,|]/).map(item => item.trim()).filter(Boolean); }
function formatDate(value) { return value ? new Date(`${value}T12:00:00`).toLocaleDateString(interfaceLocale()) : translatedText("Undated"); }
function mediaLabel(value) { return translatedText(({movie: "Movie", tv: "TV series", anime: "Anime"})[value] || value); }
function statusLabel(value) { return translatedText(String(value || "").replaceAll("_", " ").replace(/^./, character => character.toUpperCase())); }
function formatRating(value) { return value == null || value === "" ? "—" : Number(value).toLocaleString(interfaceLocale(), {minimumFractionDigits: 1, maximumFractionDigits: 1}); }
function formatRatingInput(value) { return value == null || value === "" ? "" : Number(value).toFixed(1); }
function showMessage(element, message, error = false) { setLocalizedText(element, message || ""); element.classList.toggle("error", error); }

function titleHue(title) {
  return [...String(title)].reduce((value, character, index) => value + character.charCodeAt(0) * (index + 3), 0) % 360;
}

function titleMark(title) {
  const words = String(title).trim().split(/\s+/).filter(Boolean);
  if (words.length > 1) return words.slice(0, 3).map(word => word[0]).join("");
  return (words[0] || "?").slice(0, 3);
}

function posterFallback(title, classes = "poster") {
  return `<span class="${classes} poster-fallback" style="--poster-hue:${titleHue(title)}" aria-hidden="true"><span>${esc(titleMark(title))}</span></span>`;
}

function toast(message) {
  const element = $("#toast");
  clearTimeout(toast.holdTimer);
  clearTimeout(toast.exitTimer);
  element.classList.remove("toast-exit");
  element.textContent = translatedText(message);
  element.hidden = false;
  toast.holdTimer = setTimeout(() => {
    element.classList.add("toast-exit");
    toast.exitTimer = setTimeout(() => {
      element.hidden = true;
      element.classList.remove("toast-exit");
    }, 180);
  }, 3300);
}

async function api(path, options = {}) {
  const headers = {...(options.headers || {})};
  if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {...options, headers, cache: "no-store"});
  if (!response.ok) {
    let body = {};
    try { body = await response.json(); } catch (_) { /* response was not JSON */ }
    throw new Error(body.error?.message || `Request failed (${response.status})`);
  }
  if (response.status === 204) return null;
  return response.json();
}

function themePreference() {
  try { return localStorage.getItem("watchtracker-theme") || "system"; }
  catch (_) { return "system"; }
}

function accentPreference() {
  try { return localStorage.getItem("watchtracker-accent") || "forest"; }
  catch (_) { return "forest"; }
}

function customAccentPreference() {
  try {
    const value = localStorage.getItem("watchtracker-accent-custom");
    return value && /^#[0-9a-f]{6}$/i.test(value) ? value.toLowerCase() : null;
  } catch (_) { return null; }
}

function backgroundPreference() {
  try {
    const value = localStorage.getItem("watchtracker-background");
    return value && /^#[0-9a-f]{6}$/i.test(value) ? value.toLowerCase() : null;
  } catch (_) { return null; }
}

function backgroundStrengthPreference() {
  try {
    const value = Number(localStorage.getItem("watchtracker-background-strength"));
    return Number.isFinite(value) && value >= 0 && value <= 100 ? value : 16;
  } catch (_) { return 16; }
}

function backgroundModePreference() {
  try { return localStorage.getItem("watchtracker-background-mode") === "full" ? "full" : "adaptive"; }
  catch (_) { return "adaptive"; }
}

function mediaArtworkPreference() {
  try { return localStorage.getItem("watchtracker-media-artwork-tint") === "true"; }
  catch (_) { return false; }
}

function colorTone(color) {
  const channels = color.slice(1).match(/.{2}/g).map(value => Number.parseInt(value, 16) / 255);
  const luminance = channels.map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4).reduce((total, value, index) => total + value * [0.2126, 0.7152, 0.0722][index], 0);
  return luminance < .34 ? "dark" : "light";
}

function applyBackgroundColor(color, strength = backgroundStrengthPreference(), mode = backgroundModePreference()) {
  const valid = typeof color === "string" && /^#[0-9a-f]{6}$/i.test(color);
  const selected = valid ? color.toLowerCase() : null;
  const selectedStrength = Math.max(0, Math.min(100, Number(strength) || 0));
  const selectedMode = mode === "full" ? "full" : "adaptive";
  try {
    if (selected) localStorage.setItem("watchtracker-background", selected);
    else localStorage.removeItem("watchtracker-background");
    localStorage.setItem("watchtracker-background-strength", String(selectedStrength));
    localStorage.setItem("watchtracker-background-mode", selectedMode);
  } catch (_) { /* optional */ }
  if (selected) {
    document.documentElement.dataset.customBackground = "true";
    document.documentElement.dataset.backgroundMode = selectedMode;
    document.documentElement.dataset.backgroundTone = colorTone(selected);
    document.documentElement.style.setProperty("--background-choice", selected);
    document.documentElement.style.setProperty("--background-strength", `${selectedStrength}%`);
    document.documentElement.style.setProperty("--surface-tint-strength", `${Math.max(3, selectedStrength * .55)}%`);
    document.documentElement.style.setProperty("--raised-tint-strength", `${Math.max(2, selectedStrength * .36)}%`);
    document.documentElement.style.setProperty("--line-tint-strength", `${Math.max(8, selectedStrength * .8)}%`);
  } else {
    delete document.documentElement.dataset.customBackground;
    delete document.documentElement.dataset.backgroundMode;
    delete document.documentElement.dataset.backgroundTone;
    document.documentElement.style.removeProperty("--background-choice");
  }
  if ($("#background-color")) $("#background-color").value = selected || "#6c7f78";
  if ($("#background-strength")) $("#background-strength").value = String(selectedStrength);
  if ($("#background-strength-value")) $("#background-strength-value").textContent = `${Math.round(selectedStrength)}%`;
  if ($("#background-mode")) $("#background-mode").value = selectedMode;
}

function applyMediaArtworkPreference(enabled) {
  const selected = Boolean(enabled);
  try { localStorage.setItem("watchtracker-media-artwork-tint", String(selected)); } catch (_) { /* optional */ }
  if (selected) document.documentElement.dataset.mediaArtworkTint = "true";
  else delete document.documentElement.dataset.mediaArtworkTint;
  if ($("#media-artwork-tint")) $("#media-artwork-tint").checked = selected;
}

function applyAccent(accent, customColor = undefined) {
  const valid = new Set(["forest", "ocean", "violet", "rose", "amber", "graphite"]);
  const selected = valid.has(accent) ? accent : "forest";
  const custom = customColor === undefined ? customAccentPreference() : (typeof customColor === "string" && /^#[0-9a-f]{6}$/i.test(customColor) ? customColor.toLowerCase() : null);
  try {
    localStorage.setItem("watchtracker-accent", selected);
    if (custom) localStorage.setItem("watchtracker-accent-custom", custom);
    else localStorage.removeItem("watchtracker-accent-custom");
  } catch (_) { /* optional */ }
  document.documentElement.dataset.accent = selected;
  if (custom) {
    document.documentElement.dataset.customAccent = "true";
    document.documentElement.dataset.accentTone = colorTone(custom);
    document.documentElement.style.setProperty("--accent-choice", custom);
  } else {
    delete document.documentElement.dataset.customAccent;
    delete document.documentElement.dataset.accentTone;
    document.documentElement.style.removeProperty("--accent-choice");
  }
  $$("[data-accent]").forEach(button => button.setAttribute("aria-pressed", String(!custom && button.dataset.accent === selected)));
  if ($("#accent-color")) $("#accent-color").value = custom || getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#345b4c";
}

function effectiveTheme() {
  const preference = themePreference();
  return preference === "system" ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : preference;
}

function applyTheme(preference) {
  try { localStorage.setItem("watchtracker-theme", preference); } catch (_) { /* optional */ }
  if (preference === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = preference;
  if ($("#theme-preference")) $("#theme-preference").value = preference;
  const current = effectiveTheme();
  $("#theme-toggle")?.setAttribute("aria-label", `Use ${current === "dark" ? "light" : "dark"} theme`);
  $("#theme-toggle")?.setAttribute("title", `Use ${current === "dark" ? "light" : "dark"} theme`);
}

function queueAppearanceSave(payload, message) {
  state.appearanceSave = state.appearanceSave.catch(() => {}).then(async () => {
    const status = $("#appearance-state");
    if (status) {
      status.classList.add("pending");
      status.textContent = "Saving appearance…";
    }
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        await api("/api/settings/general", {method: "PUT", body: JSON.stringify(payload)});
        if (status) {
          status.classList.remove("pending");
          status.textContent = message;
        }
        return;
      } catch (_) {
        if (attempt === 0) {
          await new Promise(resolve => setTimeout(resolve, 450));
          continue;
        }
        if (status) {
          status.classList.add("pending");
          status.textContent = "Saved on this device, but portable-backup sync is pending. Change the option once more to retry.";
        }
      }
    }
  });
  return state.appearanceSave;
}

async function saveThemePreference(preference) {
  applyTheme(preference);
  return queueAppearanceSave({theme: preference}, "Theme saved automatically.");
}

async function saveAccentPreference(accent) {
  applyAccent(accent, null);
  return queueAppearanceSave({accent, accent_color: null}, `${accent[0].toUpperCase()}${accent.slice(1)} accent saved automatically.`);
}

async function saveCustomAccentPreference(color) {
  applyAccent(accentPreference(), color);
  return queueAppearanceSave({accent_color: color}, "Custom accent saved automatically.");
}

async function saveBackgroundPreference(color, strength = backgroundStrengthPreference(), mode = backgroundModePreference()) {
  applyBackgroundColor(color, strength, mode);
  return queueAppearanceSave(
    {background_color: color || null, background_strength: strength, background_mode: mode},
    color ? "Background appearance saved automatically." : "Default background restored."
  );
}

async function saveMediaArtworkPreference(enabled) {
  applyMediaArtworkPreference(enabled);
  return queueAppearanceSave(
    {media_artwork_tint: Boolean(enabled)},
    enabled ? "Media artwork tint saved automatically." : "Media artwork tint turned off."
  );
}

function switchView(view, {persist = true, scrollTop = false} = {}) {
  state.view = view === "insights" ? "insights" : "library";
  view = state.view;
  const library = view === "library";
  const active = library ? $("#library-view") : $("#insights-view");
  $("#library-view").hidden = !library;
  $("#insights-view").hidden = library;
  active.classList.remove("view-enter");
  requestAnimationFrame(() => active.classList.add("view-enter"));
  $$(".nav-button").forEach(button => {
    const selected = button.dataset.view === view;
    button.classList.toggle("active", selected);
    if (selected) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  if (persist) persistNavigationState();
  if (!library) loadInsights();
  else if (!state.libraryLoaded && !state.libraryLoading) loadLibrary();
  if (scrollTop) requestAnimationFrame(() => {
    active.querySelector("h2")?.focus({preventScroll: true});
    window.scrollTo({top: 0, behavior: "smooth"});
  });
}

function focusQuickAdd() {
  const dialog = $("#quick-add-dialog");
  if (!dialog.open) dialog.showModal();
  setTimeout(() => $("#search-input").focus(), 80);
}

function quickOptions() {
  const value = selector => $(selector).value || null;
  const status = value("#quick-status") || "watched";
  return {
    status,
    personal_rating: value("#quick-rating") ? Number(value("#quick-rating")) : null,
    watched_date: value("#quick-date"),
    started_date: value("#quick-started"),
    finished_date: value("#quick-finished"),
    view_count: value("#quick-count") === null ? null : Number(value("#quick-count")),
    user_tags: listValue(value("#quick-tags")),
    notes: value("#quick-notes")
  };
}

function updateQuickOptionCount() {
  const values = quickOptions();
  const count = [values.status !== "watched", values.personal_rating !== null, values.watched_date, values.started_date, values.finished_date, values.view_count !== null, values.user_tags.length, values.notes].filter(Boolean).length;
  const badge = $("#quick-option-count");
  badge.hidden = count === 0;
  badge.textContent = count;
  badge.setAttribute("aria-label", `${count} optional detail${count === 1 ? "" : "s"} set`);
}

async function runSearch() {
  clearTimeout(state.searchTimer);
  state.searchTimer = null;
  const input = $("#search-input");
  const query = input.value.trim();
  const results = $("#search-results");
  $("#duplicate-actions").hidden = true;
  $("#quick-add-panel").classList.toggle("has-results", query.length >= 1);
  if (query.length < 1) {
    results.innerHTML = "";
    showMessage($("#search-state"), "");
    return;
  }
  state.searchController?.abort();
  state.searchController = new AbortController();
  showMessage($("#search-state"), "Searching…");
  try {
    const type = $("#search-type").value;
    const data = await api(`/api/search?q=${encodeURIComponent(query)}${type ? `&media_type=${type}` : ""}`, {signal: state.searchController.signal});
    showMessage($("#search-state"), data.warnings.join(" ") || (data.results.length ? `${data.results.length} result${data.results.length === 1 ? "" : "s"}` : "No provider matches. Try manual add."));
    results.innerHTML = data.results.map((item, index) => `<li><button class="search-result" data-index="${index}" style="--i:${index}">
      ${imageHtml(item.poster_url, item.title, "poster")}
      <span><strong translate="no">${esc(item.title)}</strong><small><span translate="no">${esc(item.original_title || "")} ${item.original_title ? "· " : ""}${esc(item.year || "Year unknown")}</span> · ${esc(mediaLabel(item.media_type))}</small><small translate="no">${esc((item.overview || "").slice(0, 150))}</small></span>
      <span class="provider">${esc(item.provider.replace("_", " "))}</span></button></li>`).join("");
    $$(".search-result", results).forEach(button => button.addEventListener("click", () => {
      clearTimeout(state.searchTimer);
      state.searchTimer = null;
      addSearchResult(data.results[Number(button.dataset.index)]);
    }));
    bindPosterFallbacks(results);
  } catch (error) {
    if (error.name !== "AbortError") showMessage($("#search-state"), `${error.message} You can still add manually.`, true);
  }
}

async function addSearchResult(result, ifExisting = "return_existing") {
  state.selectedResult = result;
  showMessage($("#search-state"), `Adding ${result.title}…`);
  try {
    const data = await api("/api/entries/from-search", {method: "POST", body: JSON.stringify({result, ...quickOptions(), if_existing: ifExisting})});
    if (data.duplicate && data.action === "existing") {
      const box = $("#duplicate-actions");
      box.hidden = false;
      box.innerHTML = `<strong>${esc(result.title)} is already in your library.</strong><div><button data-action="open">Open entry</button><button data-action="mark_watched">Mark watched</button><button data-action="rewatch">Add rewatch today</button></div>`;
      $("[data-action='open']", box).addEventListener("click", () => { $("#quick-add-dialog").close(); openEntry(data.entry.id); });
      $("[data-action='mark_watched']", box).addEventListener("click", () => addSearchResult(result, "mark_watched"));
      $("[data-action='rewatch']", box).addEventListener("click", () => addSearchResult(result, "rewatch"));
      showMessage($("#search-state"), "Existing title found—choose an action.");
      return;
    }
    $("#duplicate-actions").hidden = true;
    showMessage($("#search-state"), data.action === "rewatched" ? "Rewatch added." : "Added to your library.");
    toast(data.action === "rewatched" ? "Rewatch recorded" : `${result.title} saved`);
    state.page = 1;
    $("#quick-add-dialog").close();
    $("#search-input").value = "";
    $("#search-results").innerHTML = "";
    $("#quick-add-panel").classList.remove("has-results");
    await loadLibrary({focusEntryId: state.view === "library" ? data.entry.id : null});
    if (state.view === "insights") await loadInsights();
  } catch (error) { showMessage($("#search-state"), error.message, true); }
}

function libraryParams() {
  const params = new URLSearchParams({page: state.page, page_size: state.pageSize, sort: state.sort, direction: state.direction});
  Object.entries(state.filters).forEach(([key, value]) => { if (value !== "" && value !== false) params.set(key, value); });
  return params;
}

function cardHtml(entry) {
  const item = entry.catalog_item;
  const title = item.canonical_title;
  const poster = imageHtml(item.poster_url, title, "poster", `Poster for ${title}`);
  const statusOptions = ["watched", "watching", "plan_to_watch", "dropped", "rewatching"].map(value => `<option value="${value}" ${entry.status === value ? "selected" : ""}>${esc(translatedText(statusLabel(value)))}</option>`).join("");
  const genres = entry.effective_genres || [];
  const remainingGenres = Math.max(genres.length - 2, 0);
  const verifiedIdentity = Boolean(item.tmdb_movie_id || item.tmdb_tv_id || item.anilist_id || item.mal_id);
  const incomplete = !item.poster_url || !item.release_year || !verifiedIdentity;
  const highRating = Number(entry.personal_rating || 0) >= 8;
  const mediaArtwork = safeImageUrl(item.poster_url);
  return `<article class="entry-card status-${esc(entry.status)} media-${esc(item.media_type)} ${entry.deleted_at ? "deleted" : ""}" data-entry="${entry.id}" data-media-hue="${titleHue(title)}"${mediaArtwork ? ` data-media-art="${esc(mediaArtwork)}"` : ""} style="--media-hue:${titleHue(title)}">
    ${poster}<div class="entry-copy"><h3 translate="no">${esc(title)}</h3><p class="entry-meta">${esc(item.release_year || translatedText("Year unknown"))} · ${esc(translatedText(mediaLabel(item.media_type)))}${item.provider_format && item.provider_format !== item.media_type ? ` · <span translate="no">${esc(item.provider_format)}</span>` : ""}</p>
    <div class="chips"><span class="chip status-chip">${esc(translatedText(statusLabel(entry.status)))}</span>${entry.personal_rating ? `<span class="chip rating-badge ${highRating ? "high-rating" : ""}">★ ${formatRating(entry.personal_rating)}/10</span>` : ""}${genres.slice(0, 2).map(genre => `<span class="chip genre-chip" translate="no">${esc(genre)}</span>`).join("")}${remainingGenres ? `<span class="chip more-chip">+${formatInteger(remainingGenres)} ${state.interfaceLanguage === "fr" ? "autres" : "more"}</span>` : ""}${incomplete ? `<button type="button" class="chip warning-chip" data-metadata-open>⚠ ${esc(translatedText("Metadata"))}</button>` : ""}</div></div>
    <div class="inline-fields"><label>${esc(translatedText("Status"))}<select data-inline="status" ${entry.deleted_at ? "disabled" : ""}>${statusOptions}</select></label><label>${esc(translatedText("Rating"))}<input data-inline="personal_rating" type="number" min="1" max="10" step="0.1" value="${formatRatingInput(entry.personal_rating)}" placeholder="—" ${entry.deleted_at ? "disabled" : ""}></label></div>
    <div class="entry-actions"><span class="muted">${esc(countText(entry.view_count, "view", "views", "visionnage", "visionnages"))}</span><button class="quiet" data-details>${esc(translatedText("Open"))}</button></div>
  </article>`;
}

function bindPosterFallbacks(root = document) {
  $$("img[data-fallback-title]", root).forEach(image => image.addEventListener("error", () => {
    const template = document.createElement("template");
    template.innerHTML = posterFallback(image.dataset.fallbackTitle || "?", image.classList.contains("poster") ? "poster" : "");
    image.replaceWith(template.content.firstElementChild);
  }, {once: true}));
}

function librarySkeletons() {
  return Array.from({length: 8}, () => `<article class="entry-card skeleton-card" aria-hidden="true"><div class="skeleton-block skeleton-poster"></div><div class="skeleton-lines"><span class="skeleton-block"></span><span class="skeleton-block"></span><span class="skeleton-block"></span></div></article>`).join("");
}

async function loadLibrary({preserveScroll = false, focusEntryId = null, showSkeleton = true} = {}) {
  const container = $("#library");
  const requestId = ++state.libraryRequestId;
  state.libraryLoading = true;
  const scrollPosition = window.scrollY;
  container.setAttribute("aria-busy", "true");
  if (showSkeleton) container.innerHTML = librarySkeletons();
  showMessage($("#library-state"), "Loading library…");
  try {
    const data = await api(`/api/entries?${libraryParams()}`);
    if (requestId !== state.libraryRequestId) return;
    if (data.pages > 0 && state.page > data.pages) {
      state.page = data.pages;
      persistNavigationState();
      return loadLibrary({preserveScroll, focusEntryId, showSkeleton: false});
    }
    if (data.pages === 0) state.page = 1;
    state.pages = data.pages;
    state.total = data.total;
    state.libraryLoaded = true;
    persistNavigationState();
    $("#library-count").textContent = countText(data.total, "title", "titles", "titre", "titres");
    container.innerHTML = data.items.length ? data.items.map(cardHtml).join("") : `<div class="empty-state"><span class="empty-monogram" aria-hidden="true">PMT</span><h3>Nothing here yet — let’s fix that</h3><p>Build your library one title at a time, or bring an existing media log.</p><div class="empty-actions"><button data-empty-search>Search a title</button><button data-empty-import class="quiet">Import a media log</button></div></div>`;
    showMessage($("#library-state"), "");
    bindCards();
    renderPagination(data.page, data.pages, data.total);
    if (preserveScroll) requestAnimationFrame(() => window.scrollTo({top: scrollPosition}));
    if (focusEntryId) requestAnimationFrame(() => $$(".entry-card").find(card => card.dataset.entry === focusEntryId)?.querySelector("[data-details]")?.focus());
  } catch (error) {
    if (requestId !== state.libraryRequestId) return;
    state.libraryLoaded = false;
    container.innerHTML = "";
    showMessage($("#library-state"), error.message, true);
  } finally {
    if (requestId === state.libraryRequestId) {
      state.libraryLoading = false;
      container.setAttribute("aria-busy", "false");
    }
  }
}

function bindCards() {
  bindPosterFallbacks($("#library"));
  $$(".entry-card").forEach(card => {
    if (card.dataset.mediaArt) card.style.setProperty("--media-art", `url(${JSON.stringify(card.dataset.mediaArt)})`);
    const id = card.dataset.entry;
    $("[data-details]", card).addEventListener("click", () => openEntry(id));
    $("[data-metadata-open]", card)?.addEventListener("click", () => openEntry(id, "metadata"));
    card.addEventListener("click", event => {
      if (window.getSelection()?.toString().trim()) return;
      if (!event.target.closest("button, input, select, a, summary")) openEntry(id);
    });
    $$("[data-inline]", card).forEach(control => control.addEventListener("change", async () => {
      const field = control.dataset.inline;
      const value = field === "personal_rating" ? (control.value ? Number(control.value) : null) : control.value;
      control.disabled = true;
      try {
        await api(`/api/entries/${id}`, {method: "PATCH", body: JSON.stringify({[field]: value})});
        card.classList.add("entry-saved");
        toast("Entry updated");
        await new Promise(resolve => setTimeout(resolve, 420));
        await loadLibrary({preserveScroll: true, showSkeleton: false});
      } catch (error) {
        toast(error.message);
        await loadLibrary({preserveScroll: true, showSkeleton: false});
      }
    }));
  });
  $("[data-empty-search]")?.addEventListener("click", focusQuickAdd);
  $("[data-empty-import]")?.addEventListener("click", () => $("#import-dialog").showModal());
}

function paginationItems(page, pages) {
  if (pages <= 7) return Array.from({length: pages}, (_, index) => index + 1);
  const values = new Set([1, pages, page - 1, page, page + 1]);
  if (page <= 3) [2, 3, 4].forEach(value => values.add(value));
  if (page >= pages - 2) [pages - 3, pages - 2, pages - 1].forEach(value => values.add(value));
  const sorted = [...values].filter(value => value >= 1 && value <= pages).sort((a, b) => a - b);
  return sorted.flatMap((value, index) => index && value - sorted[index - 1] > 1 ? ["…", value] : [value]);
}

function renderPagination(page, pages, total) {
  const nav = $("#pagination");
  if (pages <= 1) { nav.innerHTML = ""; return; }
  const pageButtons = paginationItems(page, pages).map(value => value === "…" ? `<span aria-hidden="true">…</span>` : `<button class="quiet ${value === page ? "current" : ""}" data-page="${value}" ${value === page ? 'aria-current="page"' : ""}>${value}</button>`).join("");
  nav.innerHTML = `<button class="quiet" data-page="1" ${page === 1 ? "disabled" : ""} aria-label="First page">«</button><button class="quiet" data-page="${page - 1}" ${page === 1 ? "disabled" : ""} aria-label="Previous page">‹</button>${pageButtons}<button class="quiet" data-page="${page + 1}" ${page === pages ? "disabled" : ""} aria-label="Next page">›</button><button class="quiet" data-page="${pages}" ${page === pages ? "disabled" : ""} aria-label="Last page">»</button><span class="page-summary">Page ${page} of ${pages} · ${total} titles</span>`;
  $$("[data-page]", nav).forEach(button => button.addEventListener("click", async () => {
    state.page = Number(button.dataset.page);
    persistNavigationState();
    await loadLibrary();
    window.scrollTo({top: $(".library-toolbar").offsetTop - 80, behavior: "smooth"});
  }));
}

function selectEntryTab(name) {
  $$('[data-entry-tab]').forEach(button => {
    const selected = button.dataset.entryTab === name;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  $$('[data-entry-panel]').forEach(panel => { panel.hidden = panel.dataset.entryPanel !== name; });
}

async function openEntry(id, initialTab = "details", {ratingReview = false} = {}) {
  try {
    const entry = await api(`/api/entries/${id}`);
    state.ratingReviewMode = ratingReview;
    state.currentEntry = entry;
    $("#entry-id").value = entry.id;
    $("#entry-dialog-title").textContent = `${entry.catalog_item.canonical_title}${entry.catalog_item.release_year ? ` (${entry.catalog_item.release_year})` : ""}`;
    $("#entry-status").value = entry.status;
    $("#entry-rating").value = formatRatingInput(entry.personal_rating);
    $("#save-next-rating").hidden = !ratingReview;
    $("#entry-started").value = entry.started_date || "";
    $("#entry-finished").value = entry.finished_date || "";
    $("#entry-watched").value = entry.watched_date || "";
    $("#entry-count").value = entry.view_count;
    $("#entry-tags").value = entry.user_tags.join(", ");
    $("#entry-notes").value = entry.notes || "";
    $("#entry-genre-add").value = entry.genre_additions.join(", ");
    $("#entry-genre-remove").value = entry.genre_removals.join(", ");
    $("#entry-subgenre-add").value = entry.subgenre_additions.join(", ");
    $("#entry-subgenre-remove").value = entry.subgenre_removals.join(", ");
    $("#delete-entry").hidden = Boolean(entry.deleted_at);
    $("#restore-entry").hidden = !entry.deleted_at;
    $("#entry-metadata-query").value = entry.catalog_item.canonical_title;
    const verifiedIdentity = Boolean(entry.catalog_item.tmdb_movie_id || entry.catalog_item.tmdb_tv_id || entry.catalog_item.anilist_id || entry.catalog_item.mal_id);
    $("#entry-metadata-type").value = verifiedIdentity ? entry.catalog_item.media_type : "";
    const missing = [!entry.catalog_item.poster_url && "poster", !entry.catalog_item.release_year && "release date", !verifiedIdentity && "verified provider match", !entry.catalog_item.normalized_genres.length && "genres"].filter(Boolean);
    $("#entry-metadata-state").textContent = verifiedIdentity ? (missing.length ? `Verified identity; missing ${missing.join(", ")}. Automatic refresh is safe for this entry.` : `${entry.catalog_item.provider_source || "Provider"} identity is verified.`) : `Unresolved identity. Search suggestions are never applied until you choose the exact title.`;
    const origin = [entry.catalog_item.country, entry.catalog_item.language?.toUpperCase()].filter(Boolean).join(" · ");
    const facts = [["Type", mediaLabel(entry.catalog_item.media_type)], ["Format", entry.catalog_item.provider_format], ["Original title", entry.catalog_item.original_title && entry.catalog_item.original_title !== entry.catalog_item.canonical_title ? entry.catalog_item.original_title : null], ["Released", entry.catalog_item.release_date ? formatDate(entry.catalog_item.release_date) : entry.catalog_item.release_year], ["Runtime", entry.catalog_item.runtime_minutes ? `${entry.catalog_item.runtime_minutes} min` : null], ["Episodes", entry.catalog_item.episode_count], ["Origin / language", origin], ["Genres", entry.effective_genres.join(", ")], ["Subgenres", entry.effective_subgenres.join(", ")], ["Provider tags", entry.catalog_item.keywords.join(", ")], ["Community score", entry.catalog_item.public_score != null ? `${entry.catalog_item.public_score}/10 (not your rating)` : null], ["Provider", entry.catalog_item.provider_source?.replaceAll("_", " ")], ["Description", entry.catalog_item.overview]];
    $("#entry-metadata-facts").innerHTML = facts.filter(([, value]) => value).map(([label, value]) => `<span class="${label === "Description" ? "wide-fact" : ""}"><strong>${esc(label)}:</strong> ${esc(value)}</span>`).join("");
    $("#entry-metadata-results").innerHTML = "";
    const context = entry.import_context || {};
    $("#entry-import-context").innerHTML = Object.keys(context).length ? `<details class="import-context"><summary>Imported source details</summary><dl>${Object.entries(context).map(([key, value]) => `<dt>${esc(key.replaceAll("_", " "))}</dt><dd>${esc(Array.isArray(value) ? value.join(", ") : value)}</dd>`).join("")}</dl></details>` : "";
    $("#viewing-history").innerHTML = entry.viewing_events.length ? entry.viewing_events.map(event => `<div class="viewing-row"><span>${esc(formatDate(event.viewed_on))} <small class="muted">${esc(event.source)}</small></span><button type="button" class="danger quiet-danger" data-event="${event.id}" data-event-date="${esc(formatDate(event.viewed_on))}" aria-label="Delete viewing on ${esc(formatDate(event.viewed_on))}">Delete</button></div>`).join("") : `<p class="muted">No individual viewing dates are stored. Aggregate view count may still be known.</p>`;
    $$("[data-event]", $("#viewing-history")).forEach(button => button.addEventListener("click", () => deleteViewing(entry.id, button.dataset.event, button.dataset.eventDate)));
    showMessage($("#entry-message"), "");
    selectEntryTab(initialTab);
    if (!$("#entry-dialog").open) $("#entry-dialog").showModal();
    if (initialTab === "metadata" && !verifiedIdentity) findEntryMetadata();
  } catch (error) { toast(error.message); }
}

async function saveEntry(event) {
  event.preventDefault();
  const id = $("#entry-id").value;
  const value = selector => $(selector).value || null;
  const payload = {status: value("#entry-status"), personal_rating: value("#entry-rating") ? Number(value("#entry-rating")) : null, started_date: value("#entry-started"), finished_date: value("#entry-finished"), watched_date: value("#entry-watched"), view_count: Number(value("#entry-count") || 0), user_tags: listValue(value("#entry-tags")), notes: value("#entry-notes"), genre_additions: listValue(value("#entry-genre-add")), genre_removals: listValue(value("#entry-genre-remove")), subgenre_additions: listValue(value("#entry-subgenre-add")), subgenre_removals: listValue(value("#entry-subgenre-remove"))};
  try {
    await api(`/api/entries/${id}`, {method: "PATCH", body: JSON.stringify(payload)});
    $("#entry-dialog").close();
    toast("Changes saved");
    await loadLibrary({focusEntryId: id});
  } catch (error) { showMessage($("#entry-message"), error.message, true); }
}

function confirmAction(title, message, confirmLabel = "Confirm") {
  const dialog = $("#confirm-dialog");
  $("#confirm-title").textContent = title;
  $("#confirm-message").textContent = message;
  $("#confirm-submit").textContent = confirmLabel;
  dialog.returnValue = "";
  return new Promise(resolve => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), {once: true});
    dialog.showModal();
  });
}

async function deleteViewing(id, eventId, eventDate) {
  if (!await confirmAction("Delete viewing?", `Remove the viewing dated ${eventDate}? The aggregate view count will be adjusted.`, "Delete viewing")) return;
  try {
    await api(`/api/entries/${id}/viewings/${eventId}`, {method: "DELETE"});
    await openEntry(id, "history");
    await loadLibrary({preserveScroll: true, showSkeleton: false});
  } catch (error) { showMessage($("#entry-message"), error.message, true); }
}

async function findEntryMetadata() {
  const entry = state.currentEntry;
  if (!entry) return;
  const container = $("#entry-metadata-results");
  container.innerHTML = `<p class="muted">Searching metadata providers…</p>`;
  try {
    const query = $("#entry-metadata-query").value.trim();
    if (query.length < 1) throw new Error("Enter a title.");
    const type = $("#entry-metadata-type").value;
    state.metadataSearchController?.abort();
    state.metadataSearchController = new AbortController();
    const data = await api(`/api/search?q=${encodeURIComponent(query)}${type ? `&media_type=${type}` : ""}`, {signal: state.metadataSearchController.signal});
    const warnings = data.warnings?.length ? `<p class="hint">${esc(data.warnings.join(" "))}</p>` : "";
    container.innerHTML = warnings + (data.results.length ? data.results.slice(0, 15).map((result, index) => `<div class="metadata-result">${imageHtml(result.poster_url, result.title)}<span><strong>${esc(result.title)}</strong>${result.original_title && result.original_title !== result.title ? `<small>${esc(result.original_title)}</small>` : ""}<small class="muted">${esc(result.year || "Year unknown")} · ${esc(mediaLabel(result.media_type))}${result.provider_format ? ` · ${esc(result.provider_format)}` : ""} · ${esc(result.provider.replaceAll("_", " "))}</small>${result.overview ? `<small>${esc(result.overview.slice(0, 180))}</small>` : ""}</span><button type="button" data-metadata-result="${index}">Attach this</button></div>`).join("") : `<p class="muted">No matches. Edit the title, search all types, or keep the current manual metadata.</p>`);
    $$("[data-metadata-result]", container).forEach(button => button.addEventListener("click", () => applyEntryMetadata(data.results[Number(button.dataset.metadataResult)])));
    bindPosterFallbacks(container);
  } catch (error) { if (error.name !== "AbortError") container.innerHTML = `<p class="message error">${esc(error.message)}</p>`; }
}

async function applyEntryMetadata(result) {
  const entry = state.currentEntry;
  if (!entry) return;
  try {
    await api(`/api/entries/${entry.id}/metadata`, {method: "POST", body: JSON.stringify(result)});
    toast("Metadata attached");
    await openEntry(entry.id, "metadata");
    await loadLibrary({preserveScroll: true, showSkeleton: false});
    await updateMetadataReviewCount();
  } catch (error) { showMessage($("#entry-message"), error.message, true); }
}

async function updateMetadataReviewCount() {
  try {
    const data = await api("/api/metadata/review");
    const button = $("#review-missing-metadata");
    button.textContent = data.total ? `Review unresolved (${data.total})` : "No unresolved titles";
    button.disabled = data.total === 0;
    return data;
  } catch (_) { return null; }
}

async function reviewMissingMetadata({afterCurrent = false} = {}) {
  try {
    const suffix = afterCurrent && state.currentEntry ? `?after_entry_id=${encodeURIComponent(state.currentEntry.id)}` : "";
    const data = await api(`/api/metadata/review${suffix}`);
    if (!data.entry) {
      toast(data.total ? "No later unresolved titles in the queue" : "Every title has a verified provider identity");
      return;
    }
    $("#settings-dialog").open && $("#settings-dialog").close();
    await openEntry(data.entry.id, "metadata");
  } catch (error) { toast(error.message); }
}

async function updateRatingReviewCount() {
  try {
    const data = await api("/api/ratings/review");
    const button = $("#review-ratings");
    button.textContent = data.total ? `Review ratings (${data.total})` : "No ratings to review";
    button.disabled = data.total === 0;
    return data;
  } catch (_) { return null; }
}

async function reviewRatings({afterCurrent = false} = {}) {
  try {
    const suffix = afterCurrent && state.currentEntry ? `?after_entry_id=${encodeURIComponent(state.currentEntry.id)}` : "";
    const data = await api(`/api/ratings/review${suffix}`);
    if (!data.entry) {
      state.ratingReviewMode = false;
      $("#save-next-rating").hidden = true;
      toast(data.total ? "You reached the end of the rating queue" : "There are no rated titles to review");
      return;
    }
    $("#settings-dialog").open && $("#settings-dialog").close();
    await openEntry(data.entry.id, "details", {ratingReview: true});
    $("#entry-rating").focus();
    $("#entry-rating").select();
  } catch (error) { toast(error.message); }
}

async function saveRatingAndNext() {
  const input = $("#entry-rating");
  if (!input.reportValidity() || !state.currentEntry) return;
  const entry = state.currentEntry;
  const personalRating = input.value ? Number(input.value) : null;
  try {
    await api(`/api/entries/${entry.id}`, {method: "PATCH", body: JSON.stringify({personal_rating: personalRating})});
    toast("Rating saved");
    await loadLibrary({preserveScroll: true, showSkeleton: false});
    await updateRatingReviewCount();
    await reviewRatings({afterCurrent: true});
  } catch (error) { showMessage($("#entry-message"), error.message, true); }
}

function insightsSkeletons() {
  $("#summary-cards").innerHTML = Array.from({length: 2}, () => `<section class="summary-group"><div class="skeleton-lines"><span class="skeleton-block"></span><span class="skeleton-block"></span><span class="skeleton-block"></span></div></section>`).join("");
  $("#insights-content").innerHTML = Array.from({length: 6}, () => `<section class="insight-section skeleton-card"><div class="skeleton-lines"><span class="skeleton-block"></span><span class="skeleton-block"></span><span class="skeleton-block"></span></div></section>`).join("");
}

function summaryCard(value, label, icon, primary = false) {
  return `<div class="stat-card ${primary ? "primary-stat" : ""}"><span class="stat-icon" aria-hidden="true">${icon}</span><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`;
}

function formatRate(value) {
  return value == null ? "—" : Number(value).toLocaleString(interfaceLocale(), {style: "percent", maximumFractionDigits: 0});
}

function formatPreciseRate(value) {
  if (value == null) return "—";
  const percentage = Number(value) * 100;
  if (percentage === 0) return "0%";
  if (percentage < 0.01) return state.interfaceLanguage === "fr" ? "< 0,01 %" : "<0.01%";
  const formatted = percentage.toLocaleString(interfaceLocale(), {minimumFractionDigits: percentage < 1 ? 2 : 1, maximumFractionDigits: percentage < 1 ? 2 : 1});
  return state.interfaceLanguage === "fr" ? `${formatted} %` : `${formatted}%`;
}

function confidenceLabel(value) {
  return translatedText(({insufficient_data: "Needs more data", low: "Low", medium: "Medium", high: "High"})[value] || value);
}

function compactTable(title, rows, columns, wide = false) {
  return `<section class="insight-section ${wide ? "wide" : ""}"><h3>${esc(translatedText(title))}</h3>${rows.length ? `<div class="insight-table-wrap"><table class="responsive-table"><thead><tr>${columns.map(column => `<th>${esc(translatedText(column.label))}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${columns.map(column => `<td data-label="${esc(translatedText(column.label))}">${column.render ? column.render(row[column.key], row) : esc(row[column.key] ?? "—")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : `<p class="muted">${esc(translatedText("Not enough matching data yet."))}</p>`}</section>`;
}

function chartRows(rows, {label, value, display, detail, empty = "Not enough data yet."}) {
  if (!rows.length) return `<p class="empty-chart muted">${esc(translatedText(empty))}</p>`;
  const values = rows.map(value).filter(item => Number.isFinite(item));
  const maximum = Math.max(...values, 1);
  return `<div class="ranked-chart">${rows.map((row, index) => {
    const amount = Number(value(row) || 0);
    const width = amount ? Math.max(amount / maximum * 100, 2) : 0;
    return `<button type="button" class="chart-row" data-chart-row="${index}" aria-label="${esc(`${label(row)}: ${display(row)}`)}"><span class="chart-rank">${index + 1}</span><span class="chart-label">${esc(label(row))}</span><span class="chart-track"><span style="width:${width.toFixed(2)}%"></span></span><strong>${esc(display(row))}</strong>${detail ? `<small>${esc(detail(row))}</small>` : ""}</button>`;
  }).join("")}</div>`;
}

async function loadInsights() {
  showMessage($("#insights-state"), "Calculating insights…");
  insightsSkeletons();
  try {
    const data = await api("/api/stats");
    const summary = data.summary;
    const ratings = data.rating_profile;
    const topTitle = data.top_titles.overall[0];
    const topRewatch = data.rewatch_signals[0];
    const verifiedCoverage = data.metadata_coverage.find(row => row.name === "Verified provider identity");
    const topGenre = data.genre_affinity[0];
    const ratingHistogram = Object.entries(ratings.histogram).filter(([, count]) => count).map(([rating, count]) => ({rating: Number(rating), count}));
    const maxHistogram = Math.max(...ratingHistogram.map(item => item.count), 1);
    const histogramHtml = ratingHistogram.length ? `<div class="interactive-histogram" aria-label="${esc(translatedText("Personal rating distribution"))}">${ratingHistogram.map(item => `<button type="button" class="histogram-column" aria-label="${esc(state.interfaceLanguage === "fr" ? `${countText(item.count, "title", "titles", "titre", "titres")} notés ${formatRating(item.rating)}` : `${countText(item.count, "title", "titles", "titre", "titres")} rated ${formatRating(item.rating)}`)}"><span class="histogram-count">${formatInteger(item.count)}</span><span class="histogram-bar-wrap"><span class="histogram-bar" style="height:${Math.max(item.count / maxHistogram * 100, 3)}%"></span></span><span class="histogram-label">${formatRating(item.rating)}</span></button>`).join("")}</div>` : `<p class="empty-chart muted">${esc(translatedText("Rate completed titles to reveal your distribution."))}</p>`;
    const mediaRows = data.media_type_preferences.filter(row => row.library_count);
    const mediaTotal = mediaRows.reduce((total, row) => total + row.library_count, 0) || 1;
    const mediaStops = [];
    let mediaOffset = 0;
    mediaRows.forEach((row, index) => { const next = mediaOffset + row.library_count / mediaTotal * 100; mediaStops.push(`var(--chart-${index + 1}) ${mediaOffset}% ${next}%`); mediaOffset = next; });
    const mediaDonut = `<div class="donut-layout"><div class="donut" style="--segments:${mediaStops.length ? mediaStops.join(",") : "var(--surface-2) 0 100%"}"><span><strong>${formatInteger(summary.library_total)}</strong><small>${esc(translatedText("titles"))}</small></span></div><div class="donut-legend">${mediaRows.map((row, index) => `<div><i style="--legend:var(--chart-${index + 1})"></i><span>${esc(translatedText(mediaLabel(row.media_type)))}</span><strong>${formatInteger(row.library_count)}</strong></div>`).join("")}</div></div>`;
    $("#summary-cards").innerHTML = `<section class="summary-group overview-stats"><h3>${esc(translatedText("Library & your ratings"))}</h3><div class="stat-card-grid">${summaryCard(formatInteger(summary.library_total), translatedText("Library titles"), "🎞", true)}${summaryCard(formatInteger(summary.completed_total), translatedText("Completed"), "✓")}${summaryCard(formatInteger(data.activity.all_time_completed_viewings), translatedText("Total viewings"), "▶")}${summaryCard(formatRating(ratings.average), translatedText("Average rating"), "★")}${summaryCard(formatInteger(ratings.rated_count), translatedText("Rated titles"), "✎")}${summaryCard(formatRate(data.rewatch.rate), translatedText("Rewatch rate"), "↻")}</div></section><section class="summary-group overview-breakdown"><h3>${esc(translatedText("Visual library breakdown"))}</h3>${mediaDonut}</section>`;
    const activityMonths = data.activity.monthly.slice(-18);
    const activityChart = chartRows(activityMonths, {label: row => new Date(`${row.period}-15T12:00:00`).toLocaleDateString(interfaceLocale(), {month:"short", year:"numeric"}), value: row => row.count, display: row => formatInteger(row.count), detail: row => countText(row.count, "dated viewing", "dated viewings", "visionnage daté", "visionnages datés"), empty: "Add watched dates to reveal monthly activity."});
    const weekdayRows = data.activity.by_weekday.filter(row => row.count);
    const weekdayChart = chartRows(weekdayRows, {label: row => new Intl.DateTimeFormat(interfaceLocale(), {weekday: "short"}).format(new Date(2024, 0, 1 + Number(row.weekday_index || 0))), value: row => row.count, display: row => formatInteger(row.count)});
    const story = topTitle
      ? (state.interfaceLanguage === "fr"
        ? `Votre titre le mieux noté est ${topTitle.title} avec ${formatRating(topTitle.personal_rating)}${topGenre ? `, tandis que ${topGenre.name} domine actuellement votre profil de genres` : ""}${topRewatch ? ` et ${topRewatch.title} est votre titre le plus revisionné` : ""}.`
        : `Your highest-rated title is ${topTitle.title} at ${formatRating(topTitle.personal_rating)}${topGenre ? `, while ${topGenre.name} currently leads your genre profile` : ""}${topRewatch ? ` and ${topRewatch.title} is your most rewatched` : ""}.`)
      : translatedText("Add ratings to turn your library into a personal taste profile.");
    const preferenceColumns = [{key:"name",label:"Value",render:value => esc(translatedText(value))},{key:"completed_count",label:"Titles",render:value => formatInteger(value)},{key:"share_of_known",label:"Share",render:value => formatPreciseRate(value)},{key:"average_personal_rating",label:"Avg rating",render:value => value == null ? "—" : formatRating(value)},{key:"rated_support_count",label:"Rated",render:value => formatInteger(value)},{key:"confidence",label:"Confidence",render:value => esc(confidenceLabel(value))}];
    const affinityColumns = [{key:"name",label:"Signal",render:value => `<span translate="no">${esc(value)}</span>`},{key:"weighted_affinity",label:"Weighted share",render:value => formatPreciseRate(value)},{key:"average_personal_rating",label:"Avg rating",render:value => value == null ? "—" : formatRating(value)},{key:"support_count",label:"Titles",render:value => formatInteger(value)},{key:"rated_support_count",label:"Rated",render:value => formatInteger(value)},{key:"confidence",label:"Confidence",render:value => esc(confidenceLabel(value))}];
    const disclosure = (title, description, content) => `<details class="insight-disclosure compact-disclosure"><summary><span><strong>${esc(translatedText(title))}</strong><small>${esc(translatedText(description))}</small></span><span class="disclosure-chevron" aria-hidden="true">›</span></summary><div class="insight-detail-grid">${content}</div></details>`;

    $("#insights-content").innerHTML = `<section class="insight-story wide"><p class="eyebrow">${esc(translatedText("Your watch profile"))}</p><h3>${esc(story)}</h3><div class="story-facts"><span>${formatRate(data.completion.rate)} ${esc(translatedText("completion"))}</span><span>${formatInteger(ratings.unrated_completed_count)} ${esc(translatedText("completed but unrated"))}</span><span>${formatRate(verifiedCoverage?.coverage)} ${esc(translatedText("metadata verified"))}</span></div></section>
      <section class="viz-panel taste-explorer wide"><div class="viz-heading"><div><p class="eyebrow">${esc(translatedText("Interactive explorer"))}</p><h3>${esc(translatedText("What shapes your taste?"))}</h3></div><div class="viz-controls"><label>${esc(translatedText("Dimension"))}<select id="taste-dimension"><option value="genre">${esc(translatedText("Genres"))}</option><option value="subgenre">${esc(translatedText("Subgenres"))}</option><option value="provider">${esc(translatedText("Provider tags"))}</option></select></label><label>${esc(translatedText("Measure"))}<select id="taste-metric"><option value="weighted_affinity">${esc(translatedText("Weighted share"))}</option><option value="average_personal_rating">${esc(translatedText("Average rating"))}</option><option value="support_count">${esc(translatedText("Title count"))}</option></select></label></div></div><p id="taste-explanation" class="muted"></p><div class="taste-explorer-grid"><div id="taste-chart"></div><div id="taste-detail" class="chart-detail" aria-live="polite">${esc(translatedText("Select a bar to inspect its evidence."))}</div></div></section>
      <div class="insight-pair wide"><section class="viz-panel"><div class="viz-heading"><div><p class="eyebrow">${esc(translatedText("Personal ratings"))}</p><h3>${esc(translatedText("Your rating curve"))}</h3></div><strong>${formatRating(ratings.median)} ${esc(translatedText("median"))}</strong></div><p class="muted">${esc(translatedText(ratings.tendency))} · ${esc(countText(ratings.rated_count, "rated title", "rated titles", "titre noté", "titres notés"))}</p>${histogramHtml}</section>
      <section class="viz-panel"><p class="eyebrow">${esc(translatedText("Status snapshot"))}</p><h3>${esc(translatedText("Where your library stands"))}</h3>${chartRows(data.status_distribution, {label: row => translatedText(statusLabel(row.status)), value: row => row.count, display: row => formatInteger(row.count)})}<div class="status-foot"><span><strong>${formatInteger(summary.library_total)}</strong> ${esc(translatedText("total titles"))}</span><span><strong>${formatInteger(summary.completed_total)}</strong> ${esc(translatedText("completed"))}</span></div></section></div>
      <section class="viz-panel activity-panel wide"><div class="viz-heading"><div><p class="eyebrow">${esc(translatedText("Watch activity"))}</p><h3>${esc(translatedText("When you watched"))}</h3></div><div class="activity-totals"><strong>${formatInteger(data.activity.this_year)}</strong><span>${esc(translatedText("dated this year"))}</span><strong>${formatInteger(data.activity.undated_viewings_excluded_from_time_series)}</strong><span>${esc(translatedText("undated, kept out of timeline"))}</span></div></div><div class="activity-grid"><div><h4>${esc(translatedText("Recent months"))}</h4>${activityChart}</div><div><h4>${esc(translatedText("Days of the week"))}</h4>${weekdayChart}</div></div><p class="chart-note">${esc(translatedText("Only stored viewing dates appear here. Imported view counts without dates remain in your totals and are shown separately rather than guessed."))}</p></section>
      <section class="viz-panel"><p class="eyebrow">${esc(translatedText("Watch outcomes"))}</p><h3>${esc(translatedText("Completion and rewatches"))}</h3><div class="ring-grid"><div class="progress-ring" style="--value:${(data.completion.rate || 0) * 100}"><span><strong>${formatRate(data.completion.rate)}</strong><small>${esc(translatedText("completed"))}</small></span></div><div class="progress-ring secondary-ring" style="--value:${(data.rewatch.rate || 0) * 100}"><span><strong>${formatRate(data.rewatch.rate)}</strong><small>${esc(translatedText("rewatched"))}</small></span></div></div></section>
      <section class="viz-panel"><p class="eyebrow">${esc(translatedText("Insight readiness"))}</p><h3>${esc(translatedText("How much evidence can insights use?"))}</h3><div class="ring-grid"><div class="progress-ring" style="--value:${Math.min(ratings.rated_count / Math.max(summary.completed_total, 1), 1) * 100}"><span><strong>${formatRate(Math.min(ratings.rated_count / Math.max(summary.completed_total, 1), 1))}</strong><small>${esc(translatedText("completed titles rated"))}</small></span></div><div class="progress-ring secondary-ring" style="--value:${(verifiedCoverage?.coverage || 0) * 100}"><span><strong>${formatRate(verifiedCoverage?.coverage)}</strong><small>${esc(translatedText("metadata verified"))}</small></span></div></div><p class="chart-note">${esc(translatedText("More personal ratings strengthen taste confidence. Verified provider matches add genres and tags without guessing."))}</p></section>
      ${disclosure("Formats, origins & length", "Secondary provider attributes, minimized until you need them", `${compactTable("Formats", data.format_preferences, preferenceColumns)}${compactTable("Countries", data.country_preferences, preferenceColumns)}${compactTable("Languages", data.language_preferences, preferenceColumns)}${compactTable("Runtime patterns", data.runtime_preferences, [{key:"media_scope",label:"Scope",render:value => esc(translatedText(value))}, ...preferenceColumns])}${compactTable("Episode-count patterns", data.episode_count_preferences, preferenceColumns, true)}`)}
      ${disclosure("Titles & detailed signals", "Top titles, rewatches, positive and negative signals", `${compactTable("Top titles", data.top_titles.overall, [{key:"title",label:"Title",render:value => `<span translate="no">${esc(value)}</span>`},{key:"media_type",label:"Type",render:value => esc(translatedText(mediaLabel(value)))},{key:"personal_rating",label:"Rating",render:value => value == null ? "—" : formatRating(value)},{key:"view_count",label:"Views",render:value => formatInteger(value)}], true)}${compactTable("Most rewatched", data.rewatch_signals, [{key:"title",label:"Title",render:value => `<span translate="no">${esc(value)}</span>`},{key:"personal_rating",label:"Rating",render:value => value == null ? "—" : formatRating(value)},{key:"view_count",label:"Views",render:value => formatInteger(value)}])}${compactTable("Positive signals", data.positive_signals, [{key:"title",label:"Title",render:value => `<span translate="no">${esc(value)}</span>`},{key:"personal_rating",label:"Rating",render:value => value == null ? "—" : formatRating(value)},{key:"reason",label:"Evidence"}])}${compactTable("Negative signals", data.negative_signals, [{key:"title",label:"Title",render:value => `<span translate="no">${esc(value)}</span>`},{key:"personal_rating",label:"Rating",render:value => value == null ? "—" : formatRating(value)},{key:"reason",label:"Evidence",render:value => esc(Array.isArray(value) ? value.map(item => translatedText(item)).join(", ") : translatedText(value))}])}${compactTable("Taste evidence", data.taste_dimensions, [{key:"dimension",label:"Dimension",render:value => esc(translatedText(value.replaceAll("_", " ")))},{key:"value",label:"Value",render:value => `<span translate="no">${esc(value)}</span>`},{key:"support_count",label:"Titles",render:value => formatInteger(value)},{key:"confidence",label:"Confidence",render:value => esc(confidenceLabel(value))},{key:"representative_titles",label:"Examples",render:value => `<span translate="no">${esc(value.join(", "))}</span>`}], true)}${compactTable("Provider tag signals", data.provider_tag_affinity, affinityColumns, true)}`)}
      ${disclosure("Data quality & confidence", "Coverage, scoring definitions, and exactly how to improve confidence", `<section class="insight-section confidence-guide"><h3>${esc(translatedText("How confidence works"))}</h3><p>${esc(translatedText("For affinity rows, confidence is based on titles that both carry that signal and have a personal rating:"))} <strong>${state.interfaceLanguage === "fr" ? "0–2 données supplémentaires requises, 3–4 faible, 5–9 moyenne et 10 ou plus élevée" : "0–2 needs more data, 3–4 low, 5–9 medium, and 10+ high"}</strong>. ${esc(translatedText("Rate more titles with the same verified genre or provider tag to increase it."))}</p><p><strong>${esc(translatedText("Weighted share is different from confidence."))}</strong> ${esc(translatedText("It is that signal's share of all rating-weighted signals, after each title splits its weight across its tags. A broad library can therefore produce high confidence but a very small percentage. Small non-zero values display with decimals instead of rounding to 0%."))}</p></section>${compactTable("Metadata coverage", data.metadata_coverage, [{key:"name",label:"Field",render:value => esc(translatedText(value))},{key:"known_count",label:"Known",render:value => formatInteger(value)},{key:"eligible_count",label:"Eligible",render:value => formatInteger(value)},{key:"coverage",label:"Coverage",render:value => formatRate(value)}], true)}${compactTable("Genre affinity", data.genre_affinity, affinityColumns)}${compactTable("Subgenre affinity", data.subgenre_affinity, affinityColumns)}`)}`;

    const tasteSources = {genre: data.genre_affinity, subgenre: data.subgenre_affinity, provider: data.provider_tag_affinity};
    const renderTasteChart = () => {
      const dimension = $("#taste-dimension").value;
      const metric = $("#taste-metric").value;
      const rows = [...tasteSources[dimension]].filter(row => row[metric] != null).sort((left, right) => Number(right[metric] || 0) - Number(left[metric] || 0)).slice(0, 12);
      const metricNames = {weighted_affinity: "Weighted share", average_personal_rating: "Average rating", support_count: "Title count"};
      $("#taste-explanation").textContent = translatedText(metric === "weighted_affinity" ? "Share of all rating-weighted signals. Bars are scaled against the strongest result so small signals stay visible." : metric === "average_personal_rating" ? "Mean personal rating among rated titles carrying each signal." : "Completed titles carrying each signal.");
      $("#taste-chart").innerHTML = chartRows(rows, {label: row => row.name, value: row => row[metric], display: row => metric === "weighted_affinity" ? formatPreciseRate(row[metric]) : metric === "average_personal_rating" ? formatRating(row[metric]) : formatInteger(row[metric]), detail: row => `${countText(row.rated_support_count, "rated", "rated", "noté", "notés")} · ${confidenceLabel(row.confidence)}`});
      $$("[data-chart-row]", $("#taste-chart")).forEach(button => button.addEventListener("click", () => {
        const row = rows[Number(button.dataset.chartRow)];
        $$("[data-chart-row]", $("#taste-chart")).forEach(item => item.classList.toggle("selected", item === button));
        $("#taste-detail").innerHTML = state.interfaceLanguage === "fr"
          ? `<strong translate="no">${esc(row.name)}</strong><span>${esc(countText(row.support_count, "completed title", "completed titles", "titre terminé", "titres terminés"))} · ${esc(countText(row.rated_support_count, "rated", "rated", "noté", "notés"))} · fiabilité ${esc(confidenceLabel(row.confidence))} · part pondérée ${formatPreciseRate(row.weighted_affinity)}${row.average_personal_rating == null ? "" : ` · note moyenne ${formatRating(row.average_personal_rating)}`}</span>`
          : `<strong translate="no">${esc(row.name)}</strong><span>${esc(countText(row.support_count, "completed title", "completed titles", "titre terminé", "titres terminés"))} · ${esc(countText(row.rated_support_count, "rated", "rated", "noté", "notés"))} · ${esc(confidenceLabel(row.confidence))} confidence · ${formatPreciseRate(row.weighted_affinity)} weighted share${row.average_personal_rating == null ? "" : ` · ${formatRating(row.average_personal_rating)} average rating`}</span>`;
      }));
      const dimensionName = dimension === "provider" ? translatedText("Provider tags").toLowerCase() : translatedText(dimension === "genre" ? "Genres" : "Subgenres").toLowerCase();
      $("#taste-detail").textContent = rows.length
        ? (state.interfaceLanguage === "fr" ? `Affichage des ${formatInteger(rows.length)} principaux ${dimensionName} selon « ${translatedText(metricNames[metric]).toLowerCase()} ». Sélectionnez une barre pour plus de détails.` : `Showing the top ${formatInteger(rows.length)} ${dimensionName} by ${metricNames[metric].toLowerCase()}. Select a bar for details.`)
        : translatedText("Not enough matching metadata and ratings yet.");
    };
    $("#taste-dimension").addEventListener("change", renderTasteChart);
    $("#taste-metric").addEventListener("change", renderTasteChart);
    renderTasteChart();
    localizeTree($("#summary-cards"));
    localizeTree($("#insights-content"));
    $("#insights-updated").textContent = `${translatedText("Updated")} ${new Date().toLocaleTimeString(interfaceLocale(), {hour: "2-digit", minute: "2-digit"})}`;
    showMessage($("#insights-state"), "");
  } catch (error) {
    $("#summary-cards").innerHTML = "";
    $("#insights-content").innerHTML = "";
    showMessage($("#insights-state"), error.message, true);
  }
}

async function submitManual(event) {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  const payload = Object.fromEntries(form);
  ["release_year", "personal_rating", "view_count"].forEach(key => { payload[key] = payload[key] ? Number(payload[key]) : null; });
  ["watched_date", "started_date", "finished_date"].forEach(key => { payload[key] = payload[key] || null; });
  payload.provider_genres = listValue(payload.provider_genres);
  payload.user_tags = listValue(payload.user_tags);
  try {
    const data = await api("/api/entries/manual", {method: "POST", body: JSON.stringify(payload)});
    $("#manual-dialog").close();
    formElement.reset();
    toast(data.duplicate ? "That title is already in your library" : "Manual title added");
    if (data.duplicate) await openEntry(data.entry.id);
    await loadLibrary({focusEntryId: state.view === "library" ? data.entry.id : null});
    if (state.view === "insights") await loadInsights();
  } catch (error) { showMessage($("#manual-message"), error.message, true); }
}

async function previewImport(event) {
  event.preventDefault();
  $("#preview-id").value = "";
  $("#commit-form").hidden = true;
  showMessage($("#import-message"), "Reading and comparing…");
  try {
    const data = await api("/api/imports/preview", {method: "POST", body: new FormData(event.currentTarget)});
    const counts = data.counts;
    if (!data.preview_id) throw new Error("The server did not create an import preview. Please try again.");
    const types = Object.entries(data.media_type_breakdown || {}).map(([type, count]) => `${count} ${mediaLabel(type)}`).join(" · ");
    const correction = counts.media_type_corrections ? ` · ${counts.media_type_corrections} media type correction${counts.media_type_corrections === 1 ? "" : "s"}` : "";
    $("#import-preview").innerHTML = `<section class="insight-section"><h3>Preview</h3><p>${counts.parsed_rows} parsed · ${counts.new_entries} new · ${counts.updates} updates · ${counts.duplicates} duplicates · ${counts.conflicts} conflicts · ${counts.invalid_rows} invalid${correction}</p>${types ? `<p><strong>Detected:</strong> ${esc(types)}</p>` : ""}${data.already_imported ? `<p><strong>This exact file is already imported; commit will do nothing.</strong></p>` : ""}${data.warnings.map(warning => `<p>${esc(warning)}</p>`).join("")}${data.status_mappings.length ? `<details><summary>Status mappings</summary><ul>${data.status_mappings.map(mapping => `<li>${esc(mapping.from)} → ${esc(mapping.to)}${mapping.uncertain ? " (review needed)" : ""}</li>`).join("")}</ul></details>` : ""}${data.normalizations.length ? `<details><summary>Count normalizations</summary><ul>${data.normalizations.map(note => `<li>${esc(note)}</li>`).join("")}</ul></details>` : ""}</section>`;
    $("#preview-id").value = data.preview_id;
    $("#commit-form").hidden = false;
    showMessage($("#import-message"), "Preview only—your library has not changed.");
  } catch (error) { showMessage($("#import-message"), error.message, true); }
}

async function commitImport(event) {
  event.preventDefault();
  const previewId = $("#preview-id").value.trim();
  if (!previewId) {
    $("#commit-form").hidden = true;
    showMessage($("#import-message"), "Preview a file successfully before committing it.", true);
    return;
  }
  const policy = $("#conflict-policy").value || null;
  try {
    const data = await api(`/api/imports/${encodeURIComponent(previewId)}/commit`, {method: "POST", body: JSON.stringify({conflict_policy: policy, allow_invalid: $("#allow-invalid").checked})});
    showMessage($("#import-message"), data.status === "already_imported" ? "This file was already imported; no changes made." : `Import complete: ${data.created} created, ${data.updated} updated, ${data.viewing_events_added} viewing events added.`);
    toast("Import complete");
    await loadLibrary();
    if (state.view === "insights") await loadInsights();
    if (data.status !== "already_imported" && $("#enrich-after-import").checked) await startEnrichment();
  } catch (error) { showMessage($("#import-message"), error.message, true); }
}

function renderEnrichmentStatus(data) {
  const previous = state.enrichmentStatus;
  state.enrichmentStatus = data.status;
  const running = data.status === "running";
  const total = Number(data.total || 0);
  const processed = Number(data.processed || 0);
  const detail = data.message || (data.status === "idle" ? "No metadata fill has run yet." : "");
  const warningText = (data.warnings || []).join(" ");
  const countText = total ? ` ${processed}/${total} checked; ${data.enriched} refreshed, ${data.needs_confirmation || 0} need confirmation, ${data.failed} failed.` : "";
  $("#enrichment-status").textContent = `${detail}${countText} ${warningText}`.trim();
  $("#enrichment-progress").hidden = !running && !total;
  $("#enrichment-progress").max = Math.max(total, 1);
  $("#enrichment-progress").value = Math.min(processed, Math.max(total, 1));
  $("#start-enrichment").disabled = running;
  $("#start-enrichment").textContent = running ? "Refreshing verified…" : "Refresh verified";
  const banner = $("#enrichment-banner");
  banner.hidden = data.status === "idle";
  banner.textContent = `${running ? "Metadata fill running." : "Metadata fill finished."} ${detail}${countText} ${warningText}`.trim();
  if (previous === "running" && data.status !== "running") {
    loadLibrary();
    if (!$("#insights-view").hidden) loadInsights();
  }
}

async function pollEnrichment() {
  clearTimeout(state.enrichmentTimer);
  try {
    const data = await api("/api/metadata/enrichment");
    renderEnrichmentStatus(data);
    if (data.status === "running") state.enrichmentTimer = setTimeout(pollEnrichment, 1200);
  } catch (error) { $("#enrichment-status").textContent = error.message; }
}

async function startEnrichment() {
  clearTimeout(state.enrichmentTimer);
  try {
    const data = await api("/api/metadata/enrichment", {method: "POST", body: JSON.stringify({limit: 2000})});
    renderEnrichmentStatus(data);
    state.enrichmentTimer = setTimeout(pollEnrichment, 300);
  } catch (error) {
    showMessage($("#settings-message"), error.message, true);
    toast(error.message);
    await pollEnrichment();
  }
}

async function openSettings() {
  const dialog = $("#settings-dialog");
  $("#tmdb-token").value = "";
  $("#theme-preference").value = themePreference();
  applyAccent(accentPreference(), customAccentPreference());
  applyBackgroundColor(backgroundPreference(), backgroundStrengthPreference(), backgroundModePreference());
  applyMediaArtworkPreference(mediaArtworkPreference());
  try { $("#settings-intro").hidden = localStorage.getItem("watchtracker-settings-intro-dismissed") === "true"; } catch (_) { /* optional */ }
  $("#layout-preference").textContent = state.layout === "grid" ? "Grid" : "List";
  showMessage($("#settings-message"), "");
  dialog.showModal();
  dialog.scrollTop = 0;
  try {
    const [metadata, general] = await Promise.all([
      api("/api/settings/metadata"),
      api("/api/settings/general")
    ]);
    renderMetadataSettings(metadata);
    renderGeneralSettings(general);
    await updateMetadataReviewCount();
    await updateRatingReviewCount();
    await pollEnrichment();
  } catch (error) { showMessage($("#settings-message"), error.message, true); }
}

function renderMetadataSettings(data) {
  setLocalizedText($("#tmdb-status"), data.tmdb_configured ? "Configured" : "Not configured");
  setLocalizedText($("#anilist-status"), data.anilist_enabled ? "Enabled by developer" : "Disabled by policy");
  $("#anilist-status").classList.toggle("success-chip", Boolean(data.anilist_enabled));
  const labels = {environment: "Environment override", keychain: "Operating-system credential vault", local_secret_file: "Local configuration file", legacy_env: "Legacy .env compatibility", none: "No credential stored"};
  const englishStorage = labels[data.storage] || data.storage;
  const frenchStorage = frenchText[englishStorage] || englishStorage;
  setLocalizedText(
    $("#tmdb-storage"),
    `Credential storage: ${englishStorage}. The token is never returned to this page. The local file is easiest and avoids operating-system password prompts; the system vault provides stronger protection where available.`,
    `Stockage de l’identifiant : ${frenchStorage}. Le jeton n’est jamais renvoyé sur cette page. Le fichier local est le plus simple et évite les demandes de mot de passe du système ; le coffre système offre une meilleure protection lorsqu’il est disponible.`
  );
  const preferred = data.preferred_storage === "keychain" ? "keychain" : "local_secret_file";
  const storageControl = $(`[name="credential_storage"][value="${preferred}"]`);
  if (storageControl) storageControl.checked = true;
  $("#keychain-storage").disabled = !data.keychain_available;
  $("#copy-keychain-token").hidden = !data.keychain_available;
  $("#copy-keychain-token").textContent = "Copy existing system-vault token locally";
  $("#copy-keychain-token").title = "This explicit action checks for a token saved by an earlier version. Your operating system may ask for authentication once.";
  $("#migrate-legacy-token").hidden = !data.legacy_token_available || data.storage === "environment" || data.storage === "keychain" || data.storage === "local_secret_file";
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function renderGeneralSettings(data) {
  applyTheme(data.theme || "system");
  applyAccent(data.accent || "forest", data.accent_color || null);
  applyBackgroundColor(data.background_color || null, data.background_strength ?? 16, data.background_mode || "adaptive");
  applyMediaArtworkPreference(Boolean(data.media_artwork_tint));
  $("#general-timezone").value = data.timezone || "";
  setSelectValue($("#general-language"), data.language || "en-US");
  setSelectValue($("#general-region"), data.region || "US");
  $("#interface-language").value = data.interface_language === "fr" ? "fr" : "en";
  state.generalSettingsSnapshot = {
    timezone: $("#general-timezone").value,
    language: $("#general-language").value,
    region: $("#general-region").value,
    interfaceLanguage: $("#interface-language").value,
    effectiveTimezone: data.effective_timezone || data.timezone || "System local timezone"
  };
  updateGeneralSettingsState(false);
  $("#data-location").textContent = data.data_location;
  $("#database-size").textContent = formatBytes(data.database_size);
  $("#last-backup").textContent = data.last_backup_at ? new Date(data.last_backup_at).toLocaleString(interfaceLocale()) : translatedText("Never");
  $("#app-version").textContent = data.version;
  $("#github-link").href = data.repository_url;
  $$("#open-data-folder, #open-backups-folder, #open-logs-folder").forEach(button => { button.disabled = !data.native_actions; button.title = data.native_actions ? "" : "Available in the packaged desktop app"; });
  applyInterfaceLanguage(data.interface_language || "en");
}

function setSelectValue(select, value) {
  if (![...select.options].some(option => option.value === value)) {
    select.add(new Option(`${value} (configured)`, value));
  }
  select.value = value;
}

function generalSettingsPayload() {
  return {
    timezone: $("#general-timezone").value.trim() || null,
    language: $("#general-language").value,
    region: $("#general-region").value,
    interface_language: $("#interface-language").value
  };
}

function generalSettingsDirty() {
  if (!state.generalSettingsSnapshot) return false;
  const current = generalSettingsPayload();
  return current.timezone !== (state.generalSettingsSnapshot.timezone || null) || current.language !== state.generalSettingsSnapshot.language || current.region !== state.generalSettingsSnapshot.region || current.interface_language !== state.generalSettingsSnapshot.interfaceLanguage;
}

function updateGeneralSettingsState(forceSaved = false) {
  const dirty = generalSettingsDirty();
  $("#save-general-settings").disabled = !dirty;
  $("#reset-general-settings").disabled = !dirty;
  const status = $("#general-settings-state");
  status.classList.toggle("pending", dirty);
  const timezone = state.generalSettingsSnapshot?.effectiveTimezone || "System local timezone";
  setLocalizedText(
    status,
    dirty ? "Unsaved changes" : `Saved · Effective timezone: ${timezone}`,
    dirty ? frenchText["Unsaved changes"] : `${frenchText.Saved} · ${frenchText["Effective timezone"]} : ${frenchText[timezone] || timezone}`
  );
}

function resetGeneralSettings() {
  if (!state.generalSettingsSnapshot) return;
  $("#general-timezone").value = state.generalSettingsSnapshot.timezone;
  $("#general-language").value = state.generalSettingsSnapshot.language;
  $("#general-region").value = state.generalSettingsSnapshot.region;
  $("#interface-language").value = state.generalSettingsSnapshot.interfaceLanguage;
  applyInterfaceLanguage(state.generalSettingsSnapshot.interfaceLanguage, {persist: false});
  updateGeneralSettingsState(false);
}

async function saveSettings(event) {
  event.preventDefault();
  const token = $("#tmdb-token").value.trim();
  if (!token) { showMessage($("#settings-message"), "Paste a TMDb token before saving.", true); return; }
  try {
    const credentialStorage = $("[name='credential_storage']:checked")?.value || "local_secret_file";
    const data = await api("/api/settings/metadata", {method: "PUT", body: JSON.stringify({tmdb_token: token, credential_storage: credentialStorage})});
    $("#tmdb-token").value = "";
    renderMetadataSettings(data);
    showMessage($("#settings-message"), credentialStorage === "keychain" ? "TMDb token saved to the operating-system credential vault and activated." : "TMDb token saved in the local configuration file and activated. No operating-system password prompt is required.");
    toast("Metadata settings saved");
    if (data.tmdb_configured) await startEnrichment();
  } catch (error) { showMessage($("#settings-message"), error.message, true); }
}

async function copyExistingKeychainToken() {
  if (!await confirmAction("Check the system credential vault?", "This explicit one-time migration may make your operating system ask for authentication. If a token is found, it will be copied to the local configuration file so future launches do not need the system vault.", "Check & copy")) return;
  try {
    const data = await api("/api/settings/metadata", {method: "PUT", body: JSON.stringify({import_existing_keychain: true})});
    renderMetadataSettings(data);
    showMessage($("#settings-message"), "Existing token copied to the local configuration file. The old system-vault item was left untouched and future app launches will not query it.");
    toast("System-vault token copied locally");
  } catch (error) { showMessage($("#settings-message"), error.message, true); }
}

async function clearTmdbToken() {
  if (!await confirmAction("Clear the active TMDb token?", "Movie and TV search will be unavailable until another token is saved. If local storage is active, an older inactive system-vault item is left untouched so the app does not unexpectedly request authentication.", "Clear token")) return;
  try {
    const data = await api("/api/settings/metadata", {method: "PUT", body: JSON.stringify({clear_tmdb_token: true})});
    $("#tmdb-token").value = "";
    renderMetadataSettings(data);
    showMessage($("#settings-message"), data.tmdb_configured ? "The saved token was cleared; an environment or legacy override remains active." : "TMDb token cleared.");
  } catch (error) { showMessage($("#settings-message"), error.message, true); }
}

async function migrateLegacyToken() {
  try {
    const data = await api("/api/settings/metadata/migrate-legacy", {method: "POST", body: "{}"});
    renderMetadataSettings(data);
    showMessage($("#settings-message"), "Legacy credential copied into secure local storage. The original .env file was not deleted.");
  } catch (error) { showMessage($("#settings-message"), error.message, true); }
}

async function saveGeneralSettings(event) {
  event.preventDefault();
  if (!event.currentTarget.reportValidity()) return;
  const payload = generalSettingsPayload();
  const saveButton = $("#save-general-settings");
  saveButton.disabled = true;
  showMessage($("#settings-message"), "Saving general settings…");
  try {
    await state.appearanceSave;
    await api("/api/settings/general", {method: "PUT", body: JSON.stringify(payload)});
    renderGeneralSettings(await api("/api/settings/general"));
    updateGeneralSettingsState(true);
    showMessage(
      $("#settings-message"),
      payload.interface_language === "fr"
        ? frenchText["General settings saved and verified."]
        : "General settings saved and verified."
    );
    toast("Settings saved");
  } catch (error) {
    showMessage($("#settings-message"), error.message, true);
    updateGeneralSettingsState(false);
  }
}

async function createBackup() {
  const button = $("#create-backup");
  button.disabled = true;
  button.textContent = "Creating backup…";
  try {
    const data = await api("/api/backups", {method: "POST", body: "{}"});
    showMessage($("#settings-message"), `Backup created: ${data.filename} (${formatBytes(data.size)}).`);
    toast("Backup created safely");
    // A backup must not refresh the whole General form: the user may already
    // be editing another setting while the archive finishes in the background.
    // Updating only the backup summary preserves those unsaved form values.
    $("#last-backup").textContent = new Date(data.created_at).toLocaleString(interfaceLocale());
  } catch (error) { showMessage($("#settings-message"), `${error.message} Your library was not changed.`, true); }
  finally { button.disabled = false; button.textContent = "Create backup"; }
}

async function openFolder(kind) {
  try { await api(`/api/system/open-folder?kind=${encodeURIComponent(kind)}`, {method: "POST", body: "{}"}); }
  catch (error) { showMessage($("#settings-message"), error.message, true); }
}

async function restoreDatabase(event, importExisting = false) {
  event.preventDefault();
  const description = importExisting ? "import this existing tracker database" : "restore this backup";
  if (!await confirmAction("Replace the current library?", `Personal Media Tracker will validate and ${description}. A safety backup of the current library is created first.`, importExisting ? "Import database" : "Restore backup")) return;
  const endpoint = importExisting ? "/api/data/import-database" : "/api/backups/restore";
  showMessage($("#settings-message"), importExisting ? "Validating and importing database…" : "Validating and restoring backup…");
  try {
    const data = await api(endpoint, {method: "POST", body: new FormData(event.currentTarget)});
    toast(importExisting ? "Existing database imported" : "Backup restored");
    showMessage($("#settings-message"), `Restore complete. Safety backup: ${data.safety_backup}. Reloading…`);
    setTimeout(() => window.location.reload(), 700);
  } catch (error) { showMessage($("#settings-message"), `${error.message} The current library remains recoverable.`, true); }
}

function resetMigrationPreview() {
  state.migration = {sha256: null, summary: null};
  $("#migration-preview").hidden = true;
}

function renderMigrationPreview(data) {
  state.migration = {sha256: data.sha256, summary: data};
  const sourceLabels = {
    portable_archive: "Portable library archive",
    legacy_backup_archive: "Legacy tracker backup",
    sqlite_database: "Existing tracker database"
  };
  $("#migration-source").textContent = sourceLabels[data.source_kind] || "Tracker library";
  const details = [];
  if (data.source_application_version) details.push(`app ${data.source_application_version}`);
  if (data.created_at) details.push(new Date(data.created_at).toLocaleString(interfaceLocale()));
  details.push(formatBytes(data.size));
  $("#migration-source-detail").textContent = details.join(" · ");
  $("#migration-active-titles").textContent = Number(data.active_titles || 0).toLocaleString(interfaceLocale());
  $("#migration-viewings").textContent = Number(data.viewing_events || 0).toLocaleString(interfaceLocale());
  $("#migration-deleted-titles").textContent = Number(data.deleted_titles || 0).toLocaleString(interfaceLocale());
  $("#migration-preferences").textContent = data.preferences_included ? "Included" : "Keep current";
  $("#migration-preview").hidden = false;
}

async function inspectMigration(event) {
  event.preventDefault();
  resetMigrationPreview();
  const button = event.currentTarget.querySelector("button[type='submit']");
  button.disabled = true;
  button.textContent = "Inspecting…";
  showMessage($("#settings-message"), "Validating the migration file without changing your library…");
  try {
    const data = await api("/api/data/portable/inspect", {
      method: "POST",
      body: new FormData(event.currentTarget)
    });
    renderMigrationPreview(data);
    showMessage($("#settings-message"), "Migration file verified. Check the counts before importing.");
  } catch (error) {
    showMessage($("#settings-message"), `${error.message} Your current library was not changed.`, true);
  } finally {
    button.disabled = false;
    button.textContent = "Inspect migration file";
  }
}

async function importMigration() {
  const file = $("#migration-file").files[0];
  const preview = state.migration.summary;
  if (!file || !preview || !state.migration.sha256) {
    showMessage($("#settings-message"), "Inspect the selected migration file first.", true);
    return;
  }
  const accepted = await confirmAction(
    "Import the verified library?",
    state.interfaceLanguage === "fr" ? `Cette opération remplacera la bibliothèque actuelle par ${Number(preview.active_titles || 0).toLocaleString(interfaceLocale())} titres actifs et ${Number(preview.viewing_events || 0).toLocaleString(interfaceLocale())} événements de visionnage. Une sauvegarde de sécurité sera d’abord créée.` : `This will replace the current library with ${Number(preview.active_titles || 0).toLocaleString(interfaceLocale())} active titles and ${Number(preview.viewing_events || 0).toLocaleString(interfaceLocale())} viewing events. A safety backup is created first.`,
    "Import verified library"
  );
  if (!accepted) return;
  const form = new FormData();
  form.append("file", file);
  form.append("archive_sha256", state.migration.sha256);
  const button = $("#import-migration");
  button.disabled = true;
  button.textContent = "Importing…";
  showMessage($("#settings-message"), "Verifying again and importing the complete library…");
  try {
    const data = await api("/api/data/portable/import", {method: "POST", body: form});
    toast("Complete library imported");
    showMessage($("#settings-message"), `Import complete. Safety backup: ${data.safety_backup}. Reloading…`);
    setTimeout(() => window.location.reload(), 700);
  } catch (error) {
    showMessage($("#settings-message"), `${error.message} The current library remains recoverable.`, true);
    button.disabled = false;
    button.textContent = "Import this verified library";
  }
}

async function checkForUpdates() {
  const button = $("#check-updates");
  button.disabled = true;
  showMessage($("#update-status"), "Checking GitHub Releases…");
  try {
    const data = await api("/api/updates/check", {method: "POST", body: "{}"});
    if (data.update_available) {
      $("#update-status").innerHTML = `Version ${esc(data.latest_version)} is available. <a href="${esc(data.release_url)}" target="_blank" rel="noopener" data-external>Open the release</a>.`;
    } else showMessage($("#update-status"), `You’re up to date (version ${data.current_version}).`);
  } catch (error) { showMessage($("#update-status"), error.message, true); }
  finally { button.disabled = false; }
}

function selectSettingsTab(name) {
  $$('[data-settings-tab]').forEach(button => {
    const selected = button.dataset.settingsTab === name;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  $$('[data-settings-panel]').forEach(panel => { panel.hidden = panel.dataset.settingsPanel !== name; });
  $("#settings-dialog").scrollTo({top: 0, behavior: "auto"});
}

function showOnboardingStep(name) {
  $$('[data-onboarding-step]').forEach(panel => { panel.hidden = panel.dataset.onboardingStep !== name; });
}

async function completeOnboarding(action) {
  try { localStorage.setItem("watchtracker-onboarding-complete", "true"); } catch (_) { /* optional */ }
  $("#onboarding-dialog").close();
  if (action === "search") focusQuickAdd();
  if (action === "import") $("#import-dialog").showModal();
  if (action === "manual") $("#manual-dialog").showModal();
  try { await api("/api/settings/general", {method: "PUT", body: JSON.stringify({onboarding_complete: true})}); }
  catch (_) { /* The app remains usable if onboarding state cannot be saved. */ }
}

async function initializeOnboarding() {
  try {
    if (localStorage.getItem("watchtracker-onboarding-complete") === "true") return;
  } catch (_) { /* server preference remains the fallback */ }
  try {
    const data = await api("/api/settings/general");
    if (data.onboarding_complete) {
      try { localStorage.setItem("watchtracker-onboarding-complete", "true"); } catch (_) { /* optional */ }
      return;
    }
    showOnboardingStep("welcome");
    $("#onboarding-dialog").showModal();
  } catch (_) { /* A first-run state failure must not block the library. */ }
}

function updateFilterBadge() {
  const count = Object.entries(state.filters).filter(([key, value]) => value !== "" && value !== false && !(key === "rated" && value === "all")).length;
  const badge = $("#filter-count");
  badge.hidden = count === 0;
  badge.textContent = count;
  $("#toggle-filters").classList.toggle("active", count > 0);
}

function setLayout(layout, {persist = true} = {}) {
  state.layout = layout;
  try { localStorage.setItem("watchtracker-layout", layout); } catch (_) { /* optional */ }
  $("#library").className = `library ${layout}`;
  $$("[data-layout]").forEach(button => {
    const active = button.dataset.layout === layout;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  if (persist) persistNavigationState();
}

document.addEventListener("DOMContentLoaded", () => {
  restoreNavigationState();
  applyInterfaceLanguage(interfaceLanguagePreference());
  const localizationObserver = new MutationObserver(records => {
    if (state.interfaceLanguage !== "fr") return;
    records.forEach(record => record.addedNodes.forEach(node => localizeTree(node)));
  });
  localizationObserver.observe(document.body, {childList: true, subtree: true});
  applyTheme(themePreference());
  applyAccent(accentPreference(), customAccentPreference());
  applyBackgroundColor(backgroundPreference(), backgroundStrengthPreference(), backgroundModePreference());
  applyMediaArtworkPreference(mediaArtworkPreference());
  bindHelpTips();
  try {
    $("#timezone-options").innerHTML = Intl.supportedValuesOf("timeZone").map(zone => `<option value="${esc(zone)}"></option>`).join("");
  } catch (_) { $("#timezone-options").innerHTML = '<option value="UTC"></option><option value="America/Los_Angeles"></option><option value="America/New_York"></option><option value="Europe/London"></option><option value="Europe/Paris"></option><option value="Asia/Shanghai"></option><option value="Asia/Tokyo"></option>'; }
  setLayout(state.layout, {persist: false});
  applyNavigationControls();
  switchView(state.view, {persist: false});
  $$(".nav-button").forEach(button => button.addEventListener("click", () => switchView(button.dataset.view, {scrollTop: true})));
  $(".brand").addEventListener("click", async event => {
    event.preventDefault();
    if (state.view === "insights") await loadInsights();
    else await loadLibrary({showSkeleton: false});
    window.scrollTo({top: 0, behavior: "smooth"});
  });
  $("#quick-add-shortcut").addEventListener("click", focusQuickAdd);
  $("#theme-toggle").addEventListener("click", () => saveThemePreference(effectiveTheme() === "dark" ? "light" : "dark"));
  $("#theme-preference").addEventListener("change", event => saveThemePreference(event.currentTarget.value));
  $$("[data-accent]").forEach(button => button.addEventListener("click", () => saveAccentPreference(button.dataset.accent)));
  $("#accent-color").addEventListener("input", event => applyAccent(accentPreference(), event.currentTarget.value));
  $("#accent-color").addEventListener("change", event => saveCustomAccentPreference(event.currentTarget.value));
  $("#background-color").addEventListener("input", event => applyBackgroundColor(event.currentTarget.value, Number($("#background-strength").value), $("#background-mode").value));
  $("#background-color").addEventListener("change", event => saveBackgroundPreference(event.currentTarget.value, Number($("#background-strength").value), $("#background-mode").value));
  $("#background-strength").addEventListener("input", event => applyBackgroundColor($("#background-color").value, Number(event.currentTarget.value), $("#background-mode").value));
  $("#background-strength").addEventListener("change", event => saveBackgroundPreference($("#background-color").value, Number(event.currentTarget.value), $("#background-mode").value));
  $("#background-mode").addEventListener("change", event => saveBackgroundPreference($("#background-color").value, Number($("#background-strength").value), event.currentTarget.value));
  $("#reset-background").addEventListener("click", () => saveBackgroundPreference(null, 16, "adaptive"));
  $("#media-artwork-tint").addEventListener("change", event => saveMediaArtworkPreference(event.currentTarget.checked));
  $("#search-input").addEventListener("input", () => { clearTimeout(state.searchTimer); state.searchTimer = setTimeout(runSearch, 300); });
  $("#search-type").addEventListener("change", runSearch);
  $$("#quick-options input, #quick-options select, #quick-options textarea").forEach(control => {
    control.addEventListener("input", updateQuickOptionCount);
    control.addEventListener("change", updateQuickOptionCount);
  });
  $("#sort").addEventListener("change", event => { state.sort = event.currentTarget.value; state.page = 1; updateSortDirectionControl(); persistNavigationState(); loadLibrary(); });
  $("#sort-direction").addEventListener("click", event => {
    state.direction = state.direction === "desc" ? "asc" : "desc";
    updateSortDirectionControl();
    persistNavigationState();
    loadLibrary();
  });
  $("#page-size").addEventListener("change", event => {
    state.pageSize = Number(event.currentTarget.value);
    state.page = 1;
    try { localStorage.setItem("watchtracker-page-size", String(state.pageSize)); } catch (_) { /* optional */ }
    persistNavigationState();
    loadLibrary();
  });
  $$("[data-layout]").forEach(button => button.addEventListener("click", () => setLayout(button.dataset.layout)));
  $("#toggle-filters").addEventListener("click", () => {
    const filters = $("#library-filters");
    filters.open = !filters.open;
    $("#toggle-filters").setAttribute("aria-expanded", String(filters.open));
    if (filters.open) filters.scrollIntoView({behavior: "smooth", block: "nearest"});
  });
  $("#library-filters").addEventListener("toggle", event => $("#toggle-filters").setAttribute("aria-expanded", String(event.currentTarget.open)));
  $("#filter-form").addEventListener("submit", event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    state.filters = Object.fromEntries(form);
    state.filters.include_deleted = $("[name='include_deleted']", event.currentTarget).checked;
    state.page = 1;
    updateFilterBadge();
    persistNavigationState();
    loadLibrary();
  });
  $("#filter-form").addEventListener("reset", () => setTimeout(() => { state.filters = {}; state.page = 1; updateFilterBadge(); persistNavigationState(); loadLibrary(); }, 0));
  const entryTabs = $$("[data-entry-tab]");
  entryTabs.forEach((button, index) => {
    const name = button.dataset.entryTab;
    const panel = $(`[data-entry-panel="${name}"]`);
    button.id = `entry-tab-${name}`;
    button.setAttribute("aria-controls", `entry-panel-${name}`);
    panel.id = `entry-panel-${name}`;
    panel.setAttribute("aria-labelledby", button.id);
    button.addEventListener("click", () => {
      selectEntryTab(name);
      if (name === "metadata" && state.currentEntry && !$("#entry-metadata-results").textContent.trim()) {
        const item = state.currentEntry.catalog_item;
        if (!(item.tmdb_movie_id || item.tmdb_tv_id || item.anilist_id || item.mal_id)) findEntryMetadata();
      }
    });
    button.addEventListener("keydown", event => {
      let nextIndex = null;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % entryTabs.length;
      if (event.key === "ArrowLeft") nextIndex = (index - 1 + entryTabs.length) % entryTabs.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = entryTabs.length - 1;
      if (nextIndex === null) return;
      event.preventDefault();
      const nextTab = entryTabs[nextIndex];
      selectEntryTab(nextTab.dataset.entryTab);
      nextTab.focus();
    });
  });
  $("#entry-form").addEventListener("submit", saveEntry);
  $("#find-entry-metadata").addEventListener("click", findEntryMetadata);
  $("#entry-metadata-query").addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); findEntryMetadata(); } });
  $("#next-missing-metadata").addEventListener("click", () => reviewMissingMetadata({afterCurrent: true}));
  $("#save-next-rating").addEventListener("click", saveRatingAndNext);
  $("#add-rewatch").addEventListener("click", async () => {
    const id = $("#entry-id").value;
    try { await api(`/api/entries/${id}/viewings`, {method: "POST", body: "{}"}); toast("Rewatch added today"); await openEntry(id, "history"); await loadLibrary({preserveScroll: true, showSkeleton: false}); }
    catch (error) { showMessage($("#entry-message"), error.message, true); }
  });
  $("#delete-entry").addEventListener("click", async () => {
    const id = $("#entry-id").value;
    const title = state.currentEntry?.catalog_item.canonical_title || "this entry";
    if (!await confirmAction(`Delete ${title}?`, "The entry will move to the recoverable deleted view.", "Delete entry")) return;
    try { await api(`/api/entries/${id}`, {method: "DELETE"}); $("#entry-dialog").close(); toast("Entry deleted; enable Include deleted to restore it"); await loadLibrary(); $("#library-heading").focus?.(); }
    catch (error) { showMessage($("#entry-message"), error.message, true); }
  });
  $("#restore-entry").addEventListener("click", async () => {
    const id = $("#entry-id").value;
    try { await api(`/api/entries/${id}/restore`, {method: "POST"}); $("#entry-dialog").close(); toast("Entry restored"); await loadLibrary({focusEntryId: id}); }
    catch (error) { showMessage($("#entry-message"), error.message, true); }
  });
  $("#open-manual").addEventListener("click", () => { $("#quick-add-dialog").close(); $("#manual-dialog").showModal(); });
  $("#manual-form").addEventListener("submit", submitManual);
  $$(".cancel-dialog").forEach(button => button.addEventListener("click", () => button.closest("dialog").close()));
  $("#open-import").addEventListener("click", () => $("#import-dialog").showModal());
  $("#import-form").addEventListener("submit", previewImport);
  $("#commit-form").addEventListener("submit", commitImport);
  $("#import-form [name='file']").addEventListener("change", () => { $("#preview-id").value = ""; $("#commit-form").hidden = true; $("#import-preview").innerHTML = ""; });
  $("#open-settings").addEventListener("click", openSettings);
  $("#settings-form").addEventListener("submit", saveSettings);
  $("#general-settings-form").addEventListener("submit", saveGeneralSettings);
  $$("#general-settings-form input, #general-settings-form select").forEach(control => {
    control.addEventListener("input", () => updateGeneralSettingsState(false));
    control.addEventListener("change", () => updateGeneralSettingsState(false));
  });
  $("#interface-language").addEventListener("change", event => applyInterfaceLanguage(event.currentTarget.value, {persist: false}));
  $("#reset-general-settings").addEventListener("click", resetGeneralSettings);
  $("#dismiss-settings-intro").addEventListener("click", () => {
    $("#settings-intro").hidden = true;
    try { localStorage.setItem("watchtracker-settings-intro-dismissed", "true"); } catch (_) { /* optional */ }
  });
  $("#clear-tmdb").addEventListener("click", clearTmdbToken);
  $("#copy-keychain-token").addEventListener("click", copyExistingKeychainToken);
  $("#migrate-legacy-token").addEventListener("click", migrateLegacyToken);
  $("#show-token").addEventListener("change", event => { $("#tmdb-token").type = event.currentTarget.checked ? "text" : "password"; });
  const settingsTabs = $$('[data-settings-tab]');
  settingsTabs.forEach((button, index) => {
    const name = button.dataset.settingsTab;
    const panel = $(`[data-settings-panel="${name}"]`);
    button.id = `settings-tab-${name}`;
    button.setAttribute("aria-controls", `settings-panel-${name}`);
    panel.id = `settings-panel-${name}`;
    panel.setAttribute("aria-labelledby", button.id);
    button.addEventListener("click", () => selectSettingsTab(name));
    button.addEventListener("keydown", event => {
      let next = null;
      if (event.key === "ArrowRight") next = (index + 1) % settingsTabs.length;
      if (event.key === "ArrowLeft") next = (index - 1 + settingsTabs.length) % settingsTabs.length;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = settingsTabs.length - 1;
      if (next === null) return;
      event.preventDefault();
      selectSettingsTab(settingsTabs[next].dataset.settingsTab);
      settingsTabs[next].focus();
    });
  });
  $("#create-backup").addEventListener("click", createBackup);
  $("#open-data-folder").addEventListener("click", () => openFolder("data"));
  $("#open-backups-folder").addEventListener("click", () => openFolder("backups"));
  $("#open-logs-folder").addEventListener("click", () => openFolder("logs"));
  $("#restore-backup-form").addEventListener("submit", event => restoreDatabase(event));
  $("#import-database-form").addEventListener("submit", event => restoreDatabase(event, true));
  $("#migration-inspect-form").addEventListener("submit", inspectMigration);
  $("#migration-file").addEventListener("change", resetMigrationPreview);
  $("#import-migration").addEventListener("click", importMigration);
  $("#open-import-from-settings").addEventListener("click", () => { $("#settings-dialog").close(); $("#import-dialog").showModal(); });
  $("#copy-import-prompt").addEventListener("click", async () => {
    const prompt = $("#ai-import-prompt").textContent.trim();
    try {
      await navigator.clipboard.writeText(prompt);
      toast("Conversion prompt copied");
    } catch (_) {
      const range = document.createRange();
      range.selectNodeContents($("#ai-import-prompt"));
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(range);
      toast("Prompt selected — copy it with ⌘C or Ctrl+C");
    }
  });
  $("#check-updates").addEventListener("click", checkForUpdates);
  $("#start-enrichment").addEventListener("click", startEnrichment);
  $("#review-missing-metadata").addEventListener("click", () => reviewMissingMetadata());
  $("#review-ratings").addEventListener("click", () => reviewRatings());
  $("#refresh-insights").addEventListener("click", loadInsights);
  $$('[data-onboarding-next]').forEach(button => button.addEventListener("click", () => showOnboardingStep(button.dataset.onboardingNext)));
  $("#show-onboarding-token").addEventListener("change", event => { $("#onboarding-token").type = event.currentTarget.checked ? "text" : "password"; });
  $("#onboarding-token-form").addEventListener("submit", async event => {
    event.preventDefault();
    const token = $("#onboarding-token").value.trim();
    try {
      await api("/api/settings/metadata", {method: "PUT", body: JSON.stringify({tmdb_token: token})});
      $("#onboarding-token").value = "";
      showOnboardingStep("start");
    } catch (error) { showMessage($("#onboarding-message"), error.message, true); }
  });
  $$('[data-onboarding-action]').forEach(button => button.addEventListener("click", () => completeOnboarding(button.dataset.onboardingAction)));
  document.addEventListener("keydown", event => {
    const typing = event.target.matches("input, textarea, select, [contenteditable='true']");
    const openDialog = $("dialog[open]");
    const quickShortcut = (event.key === "/" && !typing) || (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey));
    if (quickShortcut && (!openDialog || openDialog.id === "quick-add-dialog")) { event.preventDefault(); focusQuickAdd(); return; }
    if (!typing && !openDialog && event.altKey && event.key === "1") { event.preventDefault(); switchView("library", {scrollTop: true}); return; }
    if (!typing && !openDialog && event.altKey && event.key === "2") { event.preventDefault(); switchView("insights", {scrollTop: true}); return; }
    if (!typing && !openDialog && event.key === "?") { event.preventDefault(); openSettings(); return; }
    if (typing || $("dialog[open]") || !$("#insights-view").hidden) return;
    if (event.key === "ArrowLeft" && state.page > 1) { event.preventDefault(); state.page -= 1; persistNavigationState(); loadLibrary(); }
    if (event.key === "ArrowRight" && state.page < state.pages) { event.preventDefault(); state.page += 1; persistNavigationState(); loadLibrary(); }
  });
  document.addEventListener("scroll", refreshHelpTooltipAfterScroll, true);
  window.addEventListener("resize", hideHelpTooltip);
  document.addEventListener("click", async event => {
    const menu = $(".export-menu");
    if (menu.open && !menu.contains(event.target)) menu.open = false;
    const exportLink = event.target.closest("a[href^='/api/exports/']");
    if (exportLink) {
      menu.open = false;
      if (window.pywebview?.api?.save_export) {
        event.preventDefault();
        await state.appearanceSave;
        window.pywebview.api.save_export(exportLink.href).then(saved => {
          if (saved) toast("Export saved");
          else toast("Export was not saved");
        }).catch(() => toast("Export could not be saved. Your library was not changed."));
      }
      return;
    }
    const external = event.target.closest("a[data-external]");
    if (external && window.pywebview?.api?.open_external) {
      event.preventDefault();
      window.pywebview.api.open_external(external.href);
    }
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (themePreference() === "system") { applyTheme("system"); applyBackgroundColor(backgroundPreference(), backgroundStrengthPreference(), backgroundModePreference()); } });
  window.addEventListener("popstate", () => {
    restoreNavigationState();
    setLayout(state.layout, {persist: false});
    applyNavigationControls();
    switchView(state.view, {persist: false});
    loadLibrary();
  });
  updateQuickOptionCount();
  if (!state.libraryLoading) loadLibrary();
  window.addEventListener("pageshow", () => {
    if (state.view === "library" && !state.libraryLoaded && !state.libraryLoading) loadLibrary();
  });
  setTimeout(() => {
    if (state.view === "library" && !state.libraryLoaded && !state.libraryLoading) loadLibrary();
  }, 1200);
  pollEnrichment();
  initializeOnboarding();
  api("/api/settings/general").then(data => { applyTheme(data.theme || "system"); applyAccent(data.accent || "forest", data.accent_color || null); applyBackgroundColor(data.background_color || null, data.background_strength ?? 16, data.background_mode || "adaptive"); applyMediaArtworkPreference(Boolean(data.media_artwork_tint)); applyInterfaceLanguage(data.interface_language || "en"); }).catch(() => {});
});
