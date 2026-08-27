const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function syncNativeDialogLayer() {
  if (!state.nativeWindow) return;
  const openDialogs = $$('dialog[open]');
  openDialogs.forEach(dialog => dialog.classList.remove("native-dialog-active"));
  openDialogs.at(-1)?.classList.add("native-dialog-active");
  if (openDialogs.length) document.documentElement.dataset.nativeDialogOpen = "true";
  else delete document.documentElement.dataset.nativeDialogOpen;
}

function openDialog(dialog) {
  if (!dialog || dialog.open) return;
  if (state.nativeWindow) {
    // A modal dialog enters the browser top layer and covers pywebview's drag
    // regions. Native windows use an equivalent managed non-modal layer so the
    // macOS title bar remains draggable while the app content stays blocked.
    dialog.show();
    syncNativeDialogLayer();
    return;
  }
  dialog.showModal();
}

const DEFAULT_ICON_BACKGROUND = "#111010";
const DEFAULT_ICON_TEXT = "#24cd09";

function validatedNativeClientReturnUrl() {
  try {
    const value = new URLSearchParams(window.location.search).get("client_return");
    if (!value) return null;
    const parsed = new URL(value);
    const loopback = ["127.0.0.1", "localhost", "[::1]"].includes(parsed.hostname);
    if (parsed.protocol !== "http:" || !loopback || parsed.username || parsed.password || parsed.pathname !== "/" || parsed.search || parsed.hash) return null;
    return parsed.origin;
  } catch (_) { return null; }
}

const state = {
  view: "library",
  page: 1,
  pages: 0,
  total: 0,
  sort: "recently_watched",
  direction: "desc",
  pageSize: (() => { try { const value = Number(localStorage.getItem("watchtracker-page-size")); return [24, 48, 96].includes(value) ? value : 24; } catch (_) { return 24; } })(),
  layout: "grid",
  filters: {},
  selectedResult: null,
  currentEntry: null,
  searchController: null,
  metadataSearchController: null,
  ratingReviewMode: false,
  searchTimer: null,
  librarySearchTimer: null,
  rankingsTimer: null,
  enrichmentTimer: null,
  enrichmentBannerTimer: null,
  enrichmentStatus: "idle",
  generalSettingsSnapshot: null,
  migration: {sha256: null, summary: null},
  appearanceSave: Promise.resolve(),
  accentSaveTimer: null,
  iconSaveTimer: null,
  iconPreferenceRevision: 0,
  interfaceLanguage: "en",
  libraryLoaded: false,
  libraryLoading: false,
  libraryRequestId: 0,
  currentlyWatchingLoaded: false,
  watchingScope: (() => { try { const value = localStorage.getItem("watchtracker-watching-scope"); return ["all", "watching", "rewatching", "planned"].includes(value) ? value : value === "both" ? "all" : "all"; } catch (_) { return "all"; } })(),
  activeShowsLoaded: false,
  calendarLoaded: false,
  listsLoaded: false,
  listLibraryEntries: [],
  listAvailableEntries: [],
  listPickerIndex: -1,
  listSort: "created_at",
  listSortDirection: "asc",
  listScope: (() => { try { return localStorage.getItem("watchtracker-list-scope") === "shared" ? "shared" : "own"; } catch (_) { return "own"; } })(),
  activeListId: null,
  activeList: null,
  rankingsLoaded: false,
  showEpisodeProgress: (() => { try { return localStorage.getItem("watchtracker-show-episode-progress") !== "false"; } catch (_) { return true; } })(),
  advancedRatingsEnabled: false,
  rankingMode: "technical",
  ratingRubric: null,
  currentAssessment: null,
  assessmentEntry: null,
  assessmentStep: 0,
  refinementRun: null,
  comparisonSession: {count: 0, size: 5, current: null, lastPairKey: null},
  upcomingReleases: [],
  releaseCheckMode: null,
  releasePollTimer: null,
  openSeasonId: null,
  releaseEntryId: null,
  sidebarMode: (() => { try { return localStorage.getItem("watchtracker-sidebar-mode") === "minimized" ? "minimized" : "expanded"; } catch (_) { return "expanded"; } })(),
  navigationOrder: (() => { try { return localStorage.getItem("watchtracker-navigation-order") === "reversed" ? "reversed" : "standard"; } catch (_) { return "standard"; } })(),
  keyboardShortcuts: {},
  capturingShortcut: null,
  accessMode: "local",
  nativeWindow: (() => { try { return new URLSearchParams(window.location.search).has("desktop"); } catch (_) { return false; } })(),
  nativeClientReturnUrl: validatedNativeClientReturnUrl(),
  nativeSessionHandoff: (() => {
    try {
      const value = new URLSearchParams(window.location.hash.slice(1)).get("native-session") || "";
      return /^[A-Za-z0-9_-]{32,}$/.test(value) ? value : "";
    } catch (_) { return ""; }
  })(),
  nativeHostToken: (() => {
    try {
      const fromLaunch = new URLSearchParams(window.location.hash.slice(1)).get("native-host") || "";
      if (/^[A-Za-z0-9_-]{32,}$/.test(fromLaunch)) {
        sessionStorage.setItem("pmt-native-host-token", fromLaunch);
        return fromLaunch;
      }
      const retained = sessionStorage.getItem("pmt-native-host-token") || "";
      return /^[A-Za-z0-9_-]{32,}$/.test(retained) ? retained : "";
    } catch (_) { return ""; }
  })(),
  authenticated: true,
  currentUser: null,
  serverConsoleAvailable: false,
  remoteServerProfiles: [],
  settingsPrivacyReminderDismissed: false,
  integrationsLoaded: false,
  integrationConnections: [],
  integrationProviders: [],
  selectedConnectionProvider: "tmdb",
  remoteServerCandidate: null,
  importReturnToSettings: false,
  artworkSelection: null,
  backgroundImage: {available: false, enabled: false, opacity: 24, tint: true, version: null},
  insightsController: null,
  insightsTimer: null,
  insightDrilldowns: new Map(),
  insightsFilters: {period: "year", date_from: "", date_to: "", media_type: "", genre: "", status: "", watch_kind: "all", aggregation: "auto"}
};

const navigationFilters = ["q", "media_type", "status", "genre", "year_min", "year_max", "rating_min", "rating_max", "rated", "include_deleted"];
const validSorts = new Set(["recently_watched", "recently_added", "personal_rating", "title", "release_year", "media_type"]);
const validViews = new Set(["library", "currently_watching", "active_shows", "calendar", "rankings", "lists", "list_detail", "insights", "notifications", "server_console"]);
const insightFilterKeys = ["period", "date_from", "date_to", "media_type", "genre", "status", "watch_kind", "aggregation"];

const frenchText = {
  "Library": "Bibliothèque",
  "Currently Watching": "En cours",
  "Watching": "À regarder",
  "Active Shows": "Séries actives",
  "Calendar": "Calendrier",
  "Release Calendar": "Calendrier des sorties",
  "Rankings": "Classements",
  "Ratings & Rankings": "Notes et classements",
  "Personal": "Personnel",
  "Technical": "Technique",
  "Refine rankings": "Affiner les classements",
  "Your rating": "Votre note",
  "Technical score": "Score technique",
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
  "Export could not be saved. Your library was not changed.": "L’exportation n’a pas pu être enregistrée. Votre bibliothèque n’a pas été modifiée.",
  "Active Shows": "Séries en diffusion",
  "Series dashboard": "Séries en diffusion",
  "Notifications": "Notifications",
  "Check library now": "Vérifier la bibliothèque",
  "Library release check": "Vérification des sorties de la bibliothèque",
  "Choose manual or automatic checks below.": "Choisissez ci-dessous une vérification manuelle ou automatique.",
  "When to check": "Quand vérifier",
  "Choose…": "Choisir…",
  "Only when I press Check library now": "Seulement lorsque je vérifie la bibliothèque",
  "Automatically while PMT is open": "Automatiquement lorsque PMT est ouvert",
  "Followed series": "Séries suivies",
  "Watching progress": "Progression du visionnage",
  "Up Next": "À regarder ensuite",
  "Provider schedule": "Calendrier du fournisseur",
  "Upcoming air dates": "Prochaines dates de diffusion",
  "Open calendar": "Ouvrir le calendrier",
  "What appears here": "Ce qui apparaît ici",
  "Download .ics snapshot": "Télécharger l’instantané .ics",
  "Back to Active Shows": "Retour aux séries en diffusion",
  "Your ordered favourites": "Vos favoris classés",
  "How technical scores work": "Fonctionnement des scores techniques",
  "Apply": "Appliquer",
  "Advanced rankings": "Classements avancés",
  "Your personal rating is always the anchor.": "Votre note personnelle reste toujours le point de départ.",
  "PMT never silently replaces or rewrites it.": "PMT ne la remplace et ne la modifie jamais silencieusement.",
  "The calculation at a glance": "Le calcul en bref",
  "Technical score": "Score technique",
  "Rubric adjustment": "Ajustement du questionnaire",
  "Comparison adjustment": "Ajustement des comparaisons",
  "maximum ±0.75": "maximum ±0,75",
  "Work in progress.": "Travail en cours.",
  "Structured title evidence": "Évaluation structurée du titre",
  "Direct comparisons": "Comparaisons directes",
  "Evidence coverage": "Couverture des données",
  "Rewatches": "Revisionnages",
  "Stable ordering": "Ordre stable",
  "Technical rankings are an interpretation layer over your ratings—not an objective judgment about a title.": "Les classements techniques interprètent vos notes ; ils ne constituent pas un jugement objectif sur un titre.",
  "Advanced ranking refinement": "Affinement avancé du classement",
  "How much would you like to refine?": "Quelle partie souhaitez-vous affiner ?",
  "Small focused portion": "Petite sélection ciblée",
  "Entire rated library": "Toute la bibliothèque notée",
  "Optional release tracking": "Suivi facultatif des sorties",
  "When should PMT check your library?": "Quand PMT doit-il vérifier votre bibliothèque ?",
  "Only when I ask": "Seulement lorsque je le demande",
  "Title evidence · stage 2": "Évaluation du titre · étape 2",
  "Refine title evidence": "Affiner l’évaluation du titre",
  "Optional detail & private reflection": "Détails facultatifs et réflexion privée",
  "Private reflection": "Réflexion privée",
  "Reset answers": "Réinitialiser les réponses",
  "Save draft & pause": "Enregistrer le brouillon et mettre en pause",
  "Save without changing rating": "Enregistrer sans modifier la note",
  "Keep my rating & continue": "Conserver ma note et continuer",
  "Taste calibration": "Étalonnage des préférences",
  "Which do you prefer overall?": "Lequel préférez-vous dans l’ensemble ?",
  "Prefer left": "Préférer celui de gauche",
  "Tie": "Égalité",
  "Prefer right": "Préférer celui de droite",
  "Skip this pair": "Passer cette paire",
  "Under development": "En cours de développement",
  "Release notifications": "Notifications de sorties",
  "Notifications are still under development.": "Les notifications sont encore en cours de développement.",
  "No change": "Aucun changement",
  "Not refined": "Non affiné",
  "Developing evidence": "Données en développement",
  "Supported": "Étayé",
  "Well supported": "Bien étayé",
  "Skip": "Passer",
  "Calculation status": "État du calcul",
  "Overall refinement progress": "Progression globale de l’affinement",
  "Your personal ratings remain unchanged. The process first calibrates close calls with comparisons, then records structured evidence for individual titles.": "Vos notes personnelles restent inchangées. Le processus calibre d’abord les choix serrés par des comparaisons, puis enregistre une évaluation structurée pour chaque titre.",
  "About 5 comparisons, then up to 3 titles that currently have the weakest technical evidence. A good trial or quick tune-up.": "Environ 5 comparaisons, puis jusqu’à 3 titres dont les données techniques sont actuellement les plus faibles. Idéal pour essayer ou ajuster rapidement le classement.",
  "A long, resumable process: broader comparisons followed by evidence questions for every rated title. Best statistical coverage and intended to be completed over multiple sessions.": "Un processus long et reprenable : des comparaisons plus larges, puis des questions d’évaluation pour chaque titre noté. Il offre la meilleure couverture statistique et peut être réalisé en plusieurs séances.",
  "Actual rewatch count is shown during reflection, but it never adds technical-ranking points automatically. You decide whether return value matters through an optional question.": "Le nombre réel de revisionnages est affiché pendant la réflexion, mais n’ajoute jamais automatiquement de points au classement technique. Une question facultative vous permet d’indiquer l’importance d’un futur revisionnage.",
  "Answer the core questions to create usable evidence.": "Répondez aux questions principales pour créer des données utilisables.",
  "Included only in full backups and the deliberately private advanced-ratings JSON export.": "Inclus uniquement dans les sauvegardes complètes et dans l’export JSON volontairement privé des notes avancées.",
  "Choose the title you prefer overall. These nearby comparisons refine technical order and never rewrite personal ratings.": "Choisissez le titre que vous préférez dans l’ensemble. Ces comparaisons proches affinent l’ordre technique sans jamais modifier les notes personnelles.",
  "The final result is kept between 1 and 10. Evidence coverage reduces the rubric influence, while comparison reliability uses": "Le résultat final reste compris entre 1 et 10. La couverture des données réduit l’influence du questionnaire, tandis que la fiabilité des comparaisons utilise",
  "so a few choices cannot move a title too far.": "afin que quelques choix ne déplacent pas excessivement un titre.",
  "Your answers about impact, distinctiveness, freshness, engagement, coherence, and lasting value can make a small bounded adjustment.": "Vos réponses sur l’impact, le caractère distinctif, l’originalité, l’engagement, la cohérence et la valeur durable peuvent produire un petit ajustement limité.",
  "Your choices between nearby titles help settle close ordering. Comparison influence is also bounded.": "Vos choix entre des titres proches aident à départager les classements serrés. L’influence des comparaisons est également limitée.",
  "Completed questions and comparisons determine how well supported the technical score is. “Not refined” means PMT has little or no advanced evidence for that title.": "Les questions et comparaisons terminées déterminent le niveau de données étayant le score technique. « Non affiné » signifie que PMT possède peu ou pas de données avancées pour ce titre.",
  "Stored rewatches remain useful context and future insight data, but never add automatic ranking points.": "Les revisionnages enregistrés restent un contexte utile et pourront alimenter de futurs aperçus, mais n’ajoutent jamais automatiquement de points.",
  "When scores remain tied, PMT uses deterministic tie-breaking so the list does not jump around between refreshes.": "Lorsque les scores restent égaux, PMT utilise un départage déterministe afin que la liste ne change pas arbitrairement à chaque actualisation.",
  "Only library shows with a provider-confirmed episode due in the next 60 days appear here. “Active” means an announced air date—not guaranteed streaming availability. Run a library check to discover or refresh verified TV and anime.": "Seules les séries de la bibliothèque ayant un épisode confirmé par le fournisseur dans les 60 prochains jours apparaissent ici. « En diffusion » désigne une date annoncée, sans garantir la disponibilité en streaming. Vérifiez la bibliothèque pour découvrir ou actualiser les séries et anime vérifiés.",
  "What a library check does:": "Fonctionnement de la vérification :",
  "PMT looks only at TV and anime entries with an exact TMDB TV identity, then stores their provider schedule locally. It displays a tile here only when TMDB has announced an episode within 60 days. One TMDB read-access token is enough; automatic checks run only while PMT is open.": "PMT examine uniquement les séries et anime possédant une identité TMDB TV exacte, puis enregistre localement leur calendrier. Une tuile apparaît ici seulement si TMDB annonce un épisode dans les 60 jours. Un seul jeton d’accès TMDB suffit ; les vérifications automatiques ont lieu uniquement pendant que PMT est ouvert.",
  "This button is being kept in place for the future design, but PMT will not present or manage release alerts here yet. Active Shows and the Release Calendar remain available.": "Ce bouton est conservé pour la future interface, mais PMT ne présente ni ne gère encore les alertes de sortie ici. Les séries en diffusion et le calendrier des sorties restent disponibles.",
  "Choose once now; you can change this anytime on Active Shows. Either choice keeps your library and stored schedules local.": "Choisissez maintenant ; vous pourrez modifier ce réglage à tout moment dans Séries en diffusion. Dans les deux cas, votre bibliothèque et les calendriers enregistrés restent locaux.",
  "Nothing runs in the background. Press Check library now whenever you want updated air dates.": "Rien ne s’exécute en arrière-plan. Appuyez sur Vérifier la bibliothèque lorsque vous souhaitez actualiser les dates de diffusion.",
  "Check on launch, then periodically while this app or configured server stays running. PMT stops checking when it closes.": "Vérifie au lancement, puis périodiquement tant que l’application ou le serveur configuré fonctionne. PMT arrête les vérifications à sa fermeture.",
  "Checks require a TMDB token and an exact TMDB TV match. Only shows with an announced episode in the next 60 days appear on Active Shows.": "Les vérifications nécessitent un jeton TMDB et une correspondance TMDB TV exacte. Seules les séries ayant un épisode annoncé dans les 60 prochains jours apparaissent dans Séries en diffusion.",
  "Run a library check to cache schedules for TV and anime entries with an exact TMDB TV identity. PMT places only provider-confirmed air dates here; it does not claim an episode is available to stream.": "Vérifiez la bibliothèque pour enregistrer les calendriers des séries et anime possédant une identité TMDB TV exacte. PMT affiche uniquement les dates confirmées par le fournisseur, sans prétendre qu’un épisode est disponible en streaming."
};
Object.assign(frenchText, window.PMT_LOCALES?.fr || {});
const supportedInterfaceLanguages = new Set(["en", "fr", "zh-CN"]);
const interfaceCatalogs = {
  fr: frenchText,
  "zh-CN": window.PMT_LOCALES?.["zh-CN"] || {}
};

const frenchRubricText = {
  impact: ["Quelle a été la force de son impact émotionnel ou intellectuel ?", "Peu d’impact", "Impact profond et durable"],
  distinctiveness: ["Avait-il un caractère ou une identité unique, reconnaissable entre tous ?", "Difficile à distinguer", "Identité singulière"],
  formula_freshness: ["Était-il trop conventionnel, ou utilisait-il des idées familières d’une manière nouvelle ?", "Très conventionnel", "Original ou inventif"],
  engagement: ["Avec quelle constance a-t-il retenu votre attention et votre implication ?", "Souvent peu captivant", "Totalement captivant"],
  coherence: ["Dans quelle mesure ses idées, sa réalisation, son rythme et sa fin formaient-ils un ensemble cohérent ?", "Décousu ou inégal", "Exceptionnellement cohérent"],
  lasting_value: ["À quel point vous est-il resté en mémoire par la suite ?", "À peine mémorable ensuite", "M’est fortement resté en mémoire"],
  consistency: ["Sur l’ensemble de sa durée, la qualité était-elle constante ?", "Très inégal", "Constamment réussi"],
  personal_significance: ["Quelle importance personnelle avait-il au-delà de ses qualités générales ?", "Peu important personnellement", "Profondément personnel"],
  rewatch_desire: ["Indépendamment de vos visionnages passés, à quel point souhaitez-vous y revenir ?", "Aucune envie d’y revenir", "Forte envie d’y revenir"],
  reward_vs_flaws: ["Dans quelle mesure ses qualités l’ont-elles emporté sur les défauts remarqués ?", "Les défauts dominaient", "Les qualités dominaient"],
  enjoyment: ["À quel point l’expérience vous a-t-elle satisfait ?", "Peu satisfaisante", "Extrêmement satisfaisante"],
  execution: ["Dans quelle mesure a-t-il réussi ce qu’il semblait vouloir accomplir ?", "Peu réussi", "Exceptionnellement réussi"],
  memorability: ["À quel point reste-t-il distinct dans votre mémoire ?", "S’efface rapidement", "Inoubliable"]
};
const rubricCatalogs = {
  fr: frenchRubricText,
  "zh-CN": window.PMT_RUBRICS?.["zh-CN"] || {}
};
const localizedTextOriginals = new WeakMap();
const localizedFrenchOverrides = new WeakMap();
const localizedAttributeOriginals = new WeakMap();

function interfaceLanguagePreference() {
  try {
    const value = localStorage.getItem("watchtracker-interface-language");
    return supportedInterfaceLanguages.has(value) ? value : "en";
  }
  catch (_) { return "en"; }
}

function frenchPatternText(value) {
  const patterns = [
    [/^Add (.+) to favorites$/, match => `Ajouter ${match[1]} aux favoris`],
    [/^Remove (.+) from favorites$/, match => `Retirer ${match[1]} des favoris`],
    [/^Rank (\d+), (.+)$/, match => `Rang ${match[1]}, ${match[2]}`],
    [/^Page (\d+) of (\d+) · (\d+) titles$/, match => `Page ${match[1]} sur ${match[2]} · ${match[3]} titres`],
    [/^Created (.+)$/, match => `Créée le ${match[1]}`],
    [/^Review unresolved \((\d+)\)$/, match => `Vérifier les éléments non résolus (${match[1]})`],
    [/^Review ratings \((\d+)\)$/, match => `Vérifier les notes (${match[1]})`],
    [/^(\d+) results?$/, match => `${match[1]} résultat${match[1] === "1" ? "" : "s"}`],
    [/^Adding (.+)…$/, match => `Ajout de ${match[1]}…`],
    [/^(.+) is already in your library\.$/, match => `${match[1]} est déjà dans votre bibliothèque.`],
    [/^Season (\d+)$/, match => `Saison ${match[1]}`],
    [/^First air date (.+)$/, match => `Première diffusion le ${match[1]}`],
    [/^Air date (.+)$/, match => `Date de diffusion : ${match[1]}`],
    [/^Last attempted: (.+)$/, match => `Dernière tentative : ${match[1]}`],
    [/^Last successful: (.+)$/, match => `Dernière réussite : ${match[1]}`],
    [/^Follow (.+) for episode progress$/, match => `Suivre ${match[1]} pour la progression des épisodes`],
    [/^(Collapse|Open) (specials|season \d+) episodes$/, match => `${match[1] === "Open" ? "Ouvrir" : "Réduire"} les épisodes ${match[2] === "specials" ? "hors-série" : `de la saison ${match[2].split(" ")[1]}`}`],
    [/^(.+) schedule source$/, match => `Source du calendrier : ${match[1] === "Provider" ? "fournisseur" : match[1]}`],
    [/^(\d+) watched · (\d+) released · (\d+) total known\. Future air dates never mark an episode watched\.$/, match => `${match[1]} vus · ${match[2]} sortis · ${match[3]} connus au total. Les dates futures ne marquent jamais un épisode comme vu.`],
    [/^(\d+)\/(\d+) watched$/, match => `${match[1]}/${match[2]} vus`],
    [/^Choose image for (.+)$/, match => `Choisir l’image pour ${match[1]}`],
    [/^Alternative poster (\d+) for (.+)$/, match => `Affiche alternative ${match[1]} pour ${match[2]}`],
    [/^Delete viewing on (.+)$/, match => `Supprimer le visionnage du ${match[1]}`],
    [/^Remove the viewing dated (.+)\? The aggregate view count will be adjusted\.$/, match => `Supprimer le visionnage daté du ${match[1]} ? Le nombre total de visionnages sera ajusté.`],
    [/^Prepared safely with backup (.+)\. Restart the app, then open (.+)\.$/, match => `Mode préparé en toute sécurité avec la sauvegarde ${match[1]}. Redémarrez l’application, puis ouvrez ${match[2]}.`],
    [/^Version (.+) is available\. (.+)$/, match => `La version ${match[1]} est disponible. ${translatedText(match[2])}`],
    [/^(.+) Your library was not changed\.$/, match => `${match[1]} Votre bibliothèque n’a pas été modifiée.`],
    [/^(.+) Your current library was not changed\.$/, match => `${match[1]} Votre bibliothèque actuelle n’a pas été modifiée.`],
    [/^(.+) The current library remains recoverable\.$/, match => `${match[1]} La bibliothèque actuelle reste récupérable.`],
    [/^Backup created: (.+) \((.+)\)\.$/, match => `Sauvegarde créée : ${match[1]} (${match[2]}).`],
    [/^Restore complete\. Safety backup: (.+)\. Reloading…$/, match => `Restauration terminée. Sauvegarde de sécurité : ${match[1]}. Rechargement…`],
    [/^Import complete\. Safety backup: (.+)\. Reloading…$/, match => `Importation terminée. Sauvegarde de sécurité : ${match[1]}. Rechargement…`],
    [/^That combination is already assigned to (.+)\.$/, match => `Cette combinaison est déjà attribuée à ${match[1]}.`],
    [/^(.+) saved\.$/, match => `${match[1]} enregistré.`],
    [/^(\d+) calendar feed URLs? revoked$/, match => `${match[1]} adresse${match[1] === "1" ? "" : "s"} de flux de calendrier révoquée${match[1] === "1" ? "" : "s"}`],
    [/^Version (.+) is available\.$/, match => `La version ${match[1]} est disponible.`],
    [/^You’re up to date \(version (.+)\)\.$/, match => `Vous utilisez la dernière version (${match[1]}).`]
  ];
  for (const [pattern, replacement] of patterns) {
    const match = String(value).match(pattern);
    if (match) return replacement(match);
  }
  return value;
}

function translatedText(value) {
  const translated = interfaceCatalogs[state.interfaceLanguage]?.[value];
  if (translated) return translated;
  return state.interfaceLanguage === "fr" ? frenchPatternText(value) : value;
}

function interfaceCopy(english, french, chinese = null) {
  if (state.interfaceLanguage === "fr") return frenchText[english] || french || english;
  if (state.interfaceLanguage === "zh-CN") return interfaceCatalogs[state.interfaceLanguage]?.[english] || chinese || english;
  return interfaceCatalogs[state.interfaceLanguage]?.[english] || english;
}

function interfaceLocale() {
  return state.interfaceLanguage === "fr" ? "fr-FR" : state.interfaceLanguage === "zh-CN" ? "zh-CN" : "en-US";
}

function blendHexColors(foreground, background, percentage) {
  const ratio = Math.max(0, Math.min(100, Number(percentage) || 0)) / 100;
  const channels = color => color.slice(1).match(/.{2}/g).map(value => Number.parseInt(value, 16));
  return `#${channels(foreground).map((value, index) => Math.round(value * ratio + channels(background)[index] * (1 - ratio)).toString(16).padStart(2, "0")).join("")}`;
}

function nativeWindowBackground() {
  const base = effectiveTheme() === "dark" ? "#151918" : "#f4f2ed";
  const selected = backgroundPreference();
  if (!selected) return base;
  return backgroundModePreference() === "full"
    ? selected
    : blendHexColors(selected, base, backgroundStrengthPreference());
}

function syncNativeWindowBackground() {
  if (!window.pywebview?.api?.set_window_background) return;
  requestAnimationFrame(() => {
    window.pywebview.api.set_window_background(nativeWindowBackground()).catch(() => {});
  });
}

function formatInteger(value) {
  return Number(value || 0).toLocaleString(interfaceLocale(), {maximumFractionDigits: 0});
}

function countText(count, englishSingular, englishPlural, frenchSingular, frenchPlural) {
  const english = Number(count) === 1 ? englishSingular : englishPlural;
  const label = state.interfaceLanguage === "fr"
    ? (Number(count) === 1 ? frenchSingular : frenchPlural)
    : translatedText(english);
  return `${formatInteger(count)} ${label}`;
}

function setLocalizedText(element, english, french = null) {
  element.textContent = english;
  const node = element.firstChild;
  if (!node) return;
  localizedTextOriginals.set(node, english);
  if (french) localizedFrenchOverrides.set(node, french);
  node.nodeValue = state.interfaceLanguage === "fr" ? (french || translatedText(english)) : translatedText(english);
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
    const replacement = state.interfaceLanguage === "fr"
      ? (localizedFrenchOverrides.get(node) || translatedText(trimmed))
      : translatedText(trimmed);
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
      element.setAttribute(name, translatedText(original));
    });
  });
}

function applyInterfaceLanguage(language, {persist = true} = {}) {
  const selected = supportedInterfaceLanguages.has(language) ? language : "en";
  const changed = state.interfaceLanguage !== selected;
  state.interfaceLanguage = selected;
  if (persist) {
    try { localStorage.setItem("watchtracker-interface-language", selected); } catch (_) { /* optional */ }
  }
  document.documentElement.lang = selected;
  document.title = selected === "fr" ? "Personal Media Tracker · Bibliothèque" : selected === "zh-CN" ? "Personal Media Tracker · 媒体库" : "Personal Media Tracker";
  if ($("#interface-language")) $("#interface-language").value = selected;
  const importPrompt = $("#ai-import-prompt");
  if (importPrompt) {
    if (!importPrompt.dataset.englishPrompt) importPrompt.dataset.englishPrompt = importPrompt.textContent;
    importPrompt.textContent = window.PMT_IMPORT_PROMPTS?.[selected] || importPrompt.dataset.englishPrompt;
  }
  localizeTree(document.body);
  if ($("#sort-direction")) updateSortDirectionControl();
  if ($("#insights-updated")?.textContent.trim()) {
    $("#insights-updated").textContent = `${translatedText("Updated")} ${new Date().toLocaleTimeString(interfaceLocale(), {hour: "2-digit", minute: "2-digit"})}`;
  }
  if (changed && $("#insights-content")?.childElementCount) {
    queueMicrotask(() => loadInsights());
  }
  if (changed && state.view === "library" && state.libraryLoaded) {
    queueMicrotask(() => loadLibrary({showSkeleton: false}));
  }
}

function hideHelpTooltip() {
  const tooltip = $("#floating-help-tooltip");
  if (!tooltip) return;
  tooltip.hidden = true;
  tooltip.removeAttribute("data-trigger");
}

function refreshHelpTooltipAfterScroll() {
  hideHelpTooltip();
  const focusedTip = document.activeElement?.matches?.("[data-tip]:focus-visible")
    ? document.activeElement
    : null;
  const trigger = $("[data-tip]:hover") || focusedTip;
  if (trigger) requestAnimationFrame(() => showHelpTooltip(trigger));
}

function ensureHelpTooltip(trigger = null) {
  let tooltip = $("#floating-help-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.id = "floating-help-tooltip";
    tooltip.className = "floating-help-tooltip";
    tooltip.role = "tooltip";
    tooltip.hidden = true;
    document.body.append(tooltip);
  }
  // A modal dialog occupies the browser's top layer. A tooltip left under <body>
  // can be correctly positioned yet still render behind that dialog. Keep the one
  // shared tooltip inside the active dialog while its trigger is there, then move it
  // back to <body> for page-level help.
  const host = trigger?.closest?.("dialog[open]") || document.body;
  if (tooltip.parentElement !== host) host.append(tooltip);
  return tooltip;
}

function showHelpTooltip(trigger) {
  const tooltip = ensureHelpTooltip(trigger);
  tooltip.textContent = trigger.dataset.tip || "";
  if (!tooltip.textContent) return;
  tooltip.dataset.trigger = trigger.getAttribute("aria-label") || "help";
  tooltip.hidden = false;
  const rect = trigger.getBoundingClientRect();
  const margin = 12;
  const preferredLeft = rect.left + rect.width / 2 - tooltip.offsetWidth / 2;
  tooltip.style.left = `${Math.max(margin, Math.min(preferredLeft, window.innerWidth - tooltip.offsetWidth - margin))}px`;
  const below = rect.bottom + 8;
  tooltip.style.top = `${below + tooltip.offsetHeight <= window.innerHeight - margin ? below : Math.max(margin, rect.top - tooltip.offsetHeight - 8)}px`;
}

function bindHelpTips(root = document) {
  ensureHelpTooltip();
  $$(".help-tip", root).forEach(trigger => {
    if (trigger.dataset.tooltipBound) return;
    trigger.dataset.tooltipBound = "true";
    trigger.setAttribute("aria-describedby", "floating-help-tooltip");
    trigger.addEventListener("mouseenter", () => showHelpTooltip(trigger));
    trigger.addEventListener("pointerenter", () => showHelpTooltip(trigger));
    trigger.addEventListener("mouseleave", hideHelpTooltip);
    trigger.addEventListener("pointerleave", hideHelpTooltip);
    trigger.addEventListener("focus", () => {
      if (trigger.matches(":focus-visible")) showHelpTooltip(trigger);
    });
    trigger.addEventListener("blur", hideHelpTooltip);
    trigger.addEventListener("click", event => {
      event.preventDefault();
      event.stopPropagation();
      const tooltip = $("#floating-help-tooltip");
      if (!tooltip.hidden && tooltip.dataset.trigger === trigger.getAttribute("aria-label")) hideHelpTooltip();
      else {
        showHelpTooltip(trigger);
      }
    });
  });
}

function restoreNavigationState() {
  const params = new URLSearchParams(window.location.search);
  state.view = validViews.has(params.get("view")) ? params.get("view") : "library";
  // Privileged routes are selected only after the authenticated account type is
  // known. This prevents a stale server-console URL from flashing for a regular user.
  if (state.view === "server_console" && (state.currentUser?.role !== "admin" || !state.serverConsoleAvailable)) state.view = "library";
  state.activeListId = state.view === "list_detail" ? params.get("list_id") : null;
  if (state.view === "list_detail" && !state.activeListId) state.view = "lists";
  const watchingScope = params.get("watching_scope");
  if (["all", "watching", "rewatching", "planned"].includes(watchingScope)) state.watchingScope = watchingScope;
  const page = Number(params.get("page"));
  state.page = Number.isInteger(page) && page > 0 ? page : 1;
  const sort = params.get("sort");
  state.sort = validSorts.has(sort) ? sort : "recently_watched";
  state.direction = params.get("direction") === "asc" ? "asc" : "desc";
  const pageSize = Number(params.get("page_size"));
  if ([24, 48, 96].includes(pageSize)) state.pageSize = pageSize;
  state.layout = "grid";
  state.filters = {};
  if (state.view === "insights") {
    const restored = {...state.insightsFilters};
    insightFilterKeys.forEach(key => { if (params.has(key)) restored[key] = params.get(key); });
    if (!["all", "year", "90d", "30d", "custom"].includes(restored.period)) restored.period = "year";
    if (!["all", "first", "rewatch"].includes(restored.watch_kind)) restored.watch_kind = "all";
    if (!["auto", "week", "month", "year"].includes(restored.aggregation)) restored.aggregation = "auto";
    state.insightsFilters = restored;
  } else {
    navigationFilters.forEach(key => {
      if (!params.has(key)) return;
      state.filters[key] = key === "include_deleted" ? params.get(key) === "true" : params.get(key);
    });
  }
}

function persistNavigationState({push = false} = {}) {
  const params = new URLSearchParams({
    view: state.view,
    page: String(state.page),
    sort: state.sort,
    direction: state.direction,
    page_size: String(state.pageSize)
  });
  const desktop = new URLSearchParams(window.location.search).get("desktop");
  if (state.nativeWindow && ["macos", "windows", "linux"].includes(desktop)) params.set("desktop", desktop);
  if (state.nativeClientReturnUrl) params.set("client_return", state.nativeClientReturnUrl);
  if (state.view === "insights") {
    Object.entries(state.insightsFilters).forEach(([key, value]) => {
      if (value !== "" && value != null && !(key === "watch_kind" && value === "all") && !(key === "aggregation" && value === "auto")) params.set(key, String(value));
    });
  } else {
    Object.entries(state.filters).forEach(([key, value]) => {
      if (value !== "" && value !== false && value != null && !(key === "rated" && value === "all")) params.set(key, String(value));
    });
  }
  if (state.view === "currently_watching" && state.watchingScope !== "all") params.set("watching_scope", state.watchingScope);
  if (state.view === "list_detail" && state.activeListId) params.set("list_id", state.activeListId);
  const query = params.toString();
  const method = push ? "pushState" : "replaceState";
  history[method](null, "", `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`);
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
  if ($("#library-toolbar-search")) $("#library-toolbar-search").value = state.filters.q || "";
  updateFilterBadge();
}

function applySidebarPreferences(mode = state.sidebarMode, order = state.navigationOrder, {persist = true} = {}) {
  state.sidebarMode = mode === "minimized" ? "minimized" : "expanded";
  state.navigationOrder = order === "reversed" ? "reversed" : "standard";
  document.documentElement.dataset.sidebarMode = state.sidebarMode;
  document.documentElement.dataset.navigationOrder = state.navigationOrder;
  const toggle = $("#toggle-sidebar");
  if (toggle) {
    const minimized = state.sidebarMode === "minimized";
    toggle.setAttribute("aria-label", minimized ? "Expand sidebar" : "Minimize sidebar");
    toggle.title = minimized ? "Expand sidebar" : "Minimize sidebar";
  }
  if ($("#sidebar-mode")) $("#sidebar-mode").value = state.sidebarMode;
  if ($("#navigation-order")) $("#navigation-order").value = state.navigationOrder;
  if (persist) {
    try {
      localStorage.setItem("watchtracker-sidebar-mode", state.sidebarMode);
      localStorage.setItem("watchtracker-navigation-order", state.navigationOrder);
    } catch (_) { /* optional */ }
  }
}

async function toggleSidebar() {
  const mode = state.sidebarMode === "minimized" ? "expanded" : "minimized";
  applySidebarPreferences(mode, state.navigationOrder);
  try {
    await api("/api/settings/general", {method: "PUT", body: JSON.stringify({sidebar_mode: mode})});
  } catch (error) { toast(`Sidebar changed on this device; portable preference save failed: ${error.message}`); }
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
function providerFormatLabel(value) {
  if (!value) return "";
  const english = ({scripted: "Scripted", reality: "Reality", movie: "Movie", tv: "TV", ona: "ONA", ova: "OVA", special: "Special", music: "Music"})[String(value).toLowerCase()] || value;
  return translatedText(english);
}
function viewingSourceLabel(value) {
  const source = String(value || "");
  if (source.startsWith("import:")) return `${translatedText("Imported file")} · ${source.slice(7).replaceAll("_", " ")}`;
  return translatedText(({ui: "App", integration: "Integration", api: "API", episode_tracking: "Episode tracking"})[source] || source);
}
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
  element.classList.remove("toast-progress");
  void element.offsetWidth;
  element.classList.add("toast-progress");
  if (element.showPopover && !element.matches(":popover-open")) element.showPopover();
  toast.holdTimer = setTimeout(() => {
    element.classList.add("toast-exit");
    toast.exitTimer = setTimeout(() => {
      if (element.hidePopover && element.matches(":popover-open")) element.hidePopover();
      element.hidden = true;
      element.classList.remove("toast-exit");
      element.classList.remove("toast-progress");
    }, 160);
  }, 2600);
}

async function api(path, options = {}) {
  const headers = {...(options.headers || {})};
  if (state.nativeHostToken) headers["X-PMT-Native-Host"] = state.nativeHostToken;
  if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (["POST", "PUT", "PATCH", "DELETE"].includes(String(options.method || "GET").toUpperCase())) {
    const csrf = document.cookie.split("; ").find(value => value.startsWith("pmt_csrf="))?.split("=").slice(1).join("=");
    if (csrf) headers["X-CSRF-Token"] = decodeURIComponent(csrf);
  }
  const response = await fetch(path, {...options, headers, cache: "no-store"});
  if (!response.ok) {
    let body = {};
    try { body = await response.json(); } catch (_) { /* response was not JSON */ }
    if (response.status === 401 && state.accessMode === "server") showOwnerLogin();
    throw new Error(body.error?.message || `Request failed (${response.status})`);
  }
  if (response.status === 204) return null;
  return response.json();
}

function showAuthentication(mode = "login", inviteToken = "") {
  applySignedOutAppearance();
  const dialog = $("#login-dialog");
  $("#login-section").hidden = mode !== "login";
  $("#server-bootstrap-section").hidden = mode !== "setup";
  $("#invitation-section").hidden = mode !== "invite";
  if (mode === "login") {
    $("#login-form").hidden = false;
    $("#local-host-recovery-form").hidden = true;
    $("#show-local-host-recovery").hidden = false;
  }
  if (mode === "invite") $("#invitation-form [name='token']").value = inviteToken;
  openDialog(dialog);
  const selector = mode === "setup" ? "#server-bootstrap-form [name='setup_token']" : mode === "invite" ? "#invitation-form [name='username']" : "#login-form [name='username']";
  setTimeout(() => $(selector)?.focus(), 0);
}

function showOwnerLogin() {
  showAuthentication("login");
}

async function initializeAuthentication() {
  try {
    if (state.nativeSessionHandoff) {
      const token = state.nativeSessionHandoff;
      state.nativeSessionHandoff = "";
      history.replaceState({}, "", `${window.location.pathname}${window.location.search}`);
      const adopted = await fetch("/api/v1/auth/browser/adopt", {
        method: "POST",
        cache: "no-store",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({handoff_token: token})
      });
      if (!adopted.ok) throw new Error("The saved app session could not be opened.");
    }
    const headers = state.nativeHostToken ? {"X-PMT-Native-Host": state.nativeHostToken} : {};
    const response = await fetch("/api/auth/status", {cache: "no-store", headers});
    const data = await response.json();
    state.accessMode = data.mode || "local";
    state.authenticated = Boolean(data.authenticated);
    state.serverConsoleAvailable = Boolean(data.server_console_available);
    const nativeHostNote = $("#native-server-host-note");
    if (nativeHostNote) nativeHostNote.hidden = !data.native_server_host;
    if (data.native_server_host && data.server_account_hint) {
      const username = String(data.server_account_hint.username || "");
      const displayName = String(data.server_account_hint.display_name || "");
      $("#native-server-account-hint").textContent = `${translatedText("Server-account username")}: @${username}${displayName ? ` · ${displayName}` : ""}`;
      const usernameInput = $("#login-form [name='username']");
      if (usernameInput && !usernameInput.value) usernameInput.value = username;
    }
    if (data.setup_required) {
      showAuthentication("setup");
      return false;
    }
    const invitation = new URLSearchParams(window.location.search).get("invite");
    if (state.accessMode === "server" && invitation) {
      showAuthentication("invite", invitation);
      return false;
    }
    if (state.accessMode === "server" && !state.authenticated) {
      showOwnerLogin();
      return false;
    }
    return true;
  } catch (_) {
    showMessage($("#login-message"), "The server could not be reached.", true);
    showOwnerLogin();
    return false;
  }
}

function configureSettingsForAccount() {
  const role = state.currentUser?.role;
  const legacyPersonalLibrary = role === "admin" && Boolean(state.currentUser?.legacy_personal_library);
  const allowed = role === "admin" && !legacyPersonalLibrary
    ? new Set(["general", "metadata", "data", "about"])
    : role === "member"
      ? new Set(["general", "metadata", "data", ...(state.nativeClientReturnUrl ? ["access"] : []), "shortcuts", "about"])
      : null;
  $$('[data-settings-tab]').forEach(button => {
    button.hidden = Boolean(allowed && !allowed.has(button.dataset.settingsTab));
  });
  if (allowed && !allowed.has($('[data-settings-tab][aria-selected="true"]')?.dataset.settingsTab)) selectSettingsTab("general");
}

function configureNativeClientAccess() {
  const section = $("#native-client-connection");
  if (!section || !state.nativeClientReturnUrl || state.accessMode !== "server") return;
  const panel = $('[data-settings-panel="access"]');
  [...panel.children].forEach(child => { child.hidden = child.tagName !== "H3" && child !== section; });
  section.hidden = false;
  $("#native-client-server-origin").textContent = window.location.origin;
  const returnUrl = new URL(state.nativeClientReturnUrl);
  const desktop = new URLSearchParams(window.location.search).get("desktop");
  if (desktop) returnUrl.searchParams.set("desktop", desktop);
  returnUrl.searchParams.set("open_settings", "access");
  $("#return-to-local-client-settings").href = returnUrl.href;
}

async function configureAuthenticatedExperience() {
  $$('.primary-nav .nav-button').forEach(button => { button.hidden = false; });
  if (state.accessMode !== "server") {
    document.documentElement.dataset.accountKind = "local";
    // A local library is account-free. The account control appears only after
    // this installation has a verified, enabled PMT Server device profile.
    $("#open-account").hidden = true;
    $("#open-notifications").hidden = false;
    $("#server-console-nav").hidden = true;
    autoConnectSavedServer();
    return "local";
  }
  state.currentUser = await api("/api/v1/me");
  const serverOwner = state.currentUser.role === "admin";
  const legacyPersonalLibrary = serverOwner && Boolean(state.currentUser.legacy_personal_library);
  const dedicatedServerAccount = serverOwner && !legacyPersonalLibrary;
  document.documentElement.dataset.accountKind = dedicatedServerAccount ? "server-owner" : "member";
  configureSettingsForAccount();
  configureNativeClientAccess();
  $("#open-account").hidden = dedicatedServerAccount;
  $("#open-notifications").hidden = dedicatedServerAccount;
  $("#server-console-nav").hidden = !(serverOwner && state.serverConsoleAvailable);
  $$('.primary-nav .nav-button').forEach(button => { button.hidden = dedicatedServerAccount; });
  $("#quick-add-shortcut").hidden = dedicatedServerAccount;
  $("#custom-list-navigation").hidden = dedicatedServerAccount;
  const general = await api("/api/settings/general");
  renderGeneralSettings(general);
  if (!serverOwner) {
    if (state.view === "server_console") switchView("library", {persist: true, scrollTop: true});
    loadListNotifications();
    return "member";
  }

  $("#server-owner-identity").textContent = `${state.currentUser.display_name} · @${state.currentUser.username}`;
  $("#server-console-description").textContent = translatedText(legacyPersonalLibrary
    ? "This older Shared Access account also owns a migrated personal library. PMT keeps that library available without moving or deleting its data."
    : "Manage the server, regular user accounts, access, shared metadata credentials, and backups. This dedicated server account has no media library of its own.");
  if (state.serverConsoleAvailable) {
    await loadServerReadiness();
  }
  if (legacyPersonalLibrary) {
    state.view = "library";
    switchView("library", {persist: true, scrollTop: true});
    return "legacy-owner";
  }
  state.view = state.serverConsoleAvailable ? "server_console" : "library";
  switchView(state.view, {persist: true, scrollTop: true});
  return "server-owner";
}

function renderAccountIdentity() {
  if (!state.currentUser) return;
  $("#account-display-name").textContent = state.currentUser.display_name;
  const label = state.currentUser.legacy_personal_library ? "Personal profile on the server Mac" : "Regular user";
  $("#account-username").textContent = `@${state.currentUser.username} · ${translatedText(label)}`;
  $("#account-server-address").textContent = interfaceCopy(`PMT Server: ${window.location.origin}`, `Serveur PMT : ${window.location.origin}`);
}

function applySignedOutAppearance() {
  const root = document.documentElement;
  root.dataset.accountKind = "signed-out";
  delete root.dataset.theme;
  delete root.dataset.customBackground;
  delete root.dataset.backgroundMode;
  delete root.dataset.backgroundTone;
  delete root.dataset.workspaceBackgroundImage;
  delete root.dataset.workspaceBackgroundTint;
  root.style.removeProperty("--background-choice");
  root.style.removeProperty("--workspace-background-image");
  root.style.setProperty("--accent-choice", "#345b4c");
  root.style.setProperty("--accent", "#345b4c");
  root.style.setProperty("--accent-hover", "#29483c");
  root.style.setProperty("--accent-soft", "color-mix(in srgb, #345b4c 16%, var(--surface))");
  root.style.setProperty("--accent-2", "#496b73");
  root.style.setProperty("--accent-2-soft", "color-mix(in srgb, #345b4c 12%, var(--surface))");
  root.style.setProperty("--accent-ink", "#ffffff");
  syncNativeWindowBackground();
}

async function loadAccountSessions() {
  const container = $("#account-session-list");
  container.innerHTML = `<p class="muted">Loading signed-in devices…</p>`;
  try {
    const data = await api("/api/v1/auth/sessions");
    container.innerHTML = (data.items || []).map(item => `<article class="account-session"><div><strong>${esc(item.device_label || translatedText("Unknown device"))}</strong><p class="muted">${esc(translatedText(item.kind === "native" ? "Installed app" : "Web browser"))} · ${esc(translatedText("Last used"))} ${esc(new Date(item.last_seen_at).toLocaleString(interfaceLocale()))}</p></div><button type="button" class="quiet-danger" data-end-account-session="${esc(item.id)}">${esc(translatedText("End session"))}</button></article>`).join("") || `<p class="muted">${esc(translatedText("No active sessions were found."))}</p>`;
  } catch (error) { showMessage($("#account-message"), error.message, true); }
}

async function openAccount() {
  if (state.accessMode !== "server") {
    const active = state.remoteServerProfiles.find(profile => profile.enabled);
    if (active) await openDeviceServerAccount(active.id);
    return;
  }
  renderAccountIdentity();
  showMessage($("#account-message"), "");
  openDialog($("#account-dialog"));
  await loadAccountSessions();
}

async function endAccountSession(event) {
  const button = event.target.closest("[data-end-account-session]");
  if (!button) return;
  if (!await confirmAction("End this signed-in session?", "That browser or app will have to sign in again. Your account, library, ratings, and notes are not deleted.", "End session")) return;
  try {
    await api(`/api/v1/auth/sessions/${button.dataset.endAccountSession}`, {method: "DELETE"});
    await loadAccountSessions();
    toast("Session ended");
  } catch (error) { showMessage($("#account-message"), error.message, true); }
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

function mediaArtworkFullColorPreference() {
  try { return localStorage.getItem("watchtracker-media-artwork-full-color") === "true"; }
  catch (_) { return false; }
}

function episodeProgressPreference() {
  try { return localStorage.getItem("watchtracker-show-episode-progress") !== "false"; }
  catch (_) { return true; }
}

function iconColorPreference(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    return value && /^#[0-9a-f]{6}$/i.test(value) ? value.toLowerCase() : fallback;
  } catch (_) { return fallback; }
}

function iconFollowAccentPreference() {
  try { return localStorage.getItem("watchtracker-icon-follow-accent") === "true"; }
  catch (_) { return false; }
}

function effectiveAccentColor() {
  return customAccentPreference() || "#345b4c";
}

function syncNativeApplicationIcon(backgroundColor, textColor) {
  if (!window.pywebview?.api?.set_application_icon) return;
  window.pywebview.api.set_application_icon(backgroundColor, textColor).catch(() => {});
}

function applyIconPreference(
  backgroundColor = iconColorPreference("watchtracker-icon-background", DEFAULT_ICON_BACKGROUND),
  textColor = iconColorPreference("watchtracker-icon-text", DEFAULT_ICON_TEXT),
  followAccent = iconFollowAccentPreference()
) {
  const background = /^#[0-9a-f]{6}$/i.test(backgroundColor || "") ? backgroundColor.toLowerCase() : DEFAULT_ICON_BACKGROUND;
  const savedTextColor = /^#[0-9a-f]{6}$/i.test(textColor || "") ? textColor.toLowerCase() : DEFAULT_ICON_TEXT;
  const followsAccent = Boolean(followAccent);
  const textColorValue = followsAccent ? effectiveAccentColor() : savedTextColor;
  try {
    localStorage.setItem("watchtracker-icon-background", background);
    localStorage.setItem("watchtracker-icon-text", savedTextColor);
    localStorage.setItem("watchtracker-icon-follow-accent", String(followsAccent));
  } catch (_) { /* optional */ }
  if (followsAccent) document.documentElement.dataset.iconFollowsAccent = "true";
  else delete document.documentElement.dataset.iconFollowsAccent;
  document.documentElement.style.setProperty("--icon-background", background);
  document.documentElement.style.setProperty("--icon-text", textColorValue);
  if ($("#icon-background-color")) $("#icon-background-color").value = background;
  if ($("#icon-text-color")) {
    $("#icon-text-color").value = savedTextColor;
    $("#icon-text-color").disabled = followsAccent;
  }
  if ($("#icon-follow-accent")) $("#icon-follow-accent").checked = followsAccent;
  const favicon = $("#app-favicon");
  if (favicon) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="15" fill="${background}"/><text x="32" y="38" fill="${textColorValue}" font-family="Arial,sans-serif" font-size="19" font-weight="800" letter-spacing="1" text-anchor="middle">PMT</text></svg>`;
    favicon.href = `data:image/svg+xml,${encodeURIComponent(svg)}`;
  }
  syncNativeApplicationIcon(background, textColorValue);
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
  syncNativeWindowBackground();
}

function applyMediaArtworkPreference(enabled) {
  const selected = Boolean(enabled);
  try { localStorage.setItem("watchtracker-media-artwork-tint", String(selected)); } catch (_) { /* optional */ }
  if (selected) document.documentElement.dataset.mediaArtworkTint = "true";
  else delete document.documentElement.dataset.mediaArtworkTint;
  if ($("#media-artwork-tint")) $("#media-artwork-tint").checked = selected;
}

function applyMediaArtworkFullColorPreference(enabled) {
  const selected = Boolean(enabled);
  try { localStorage.setItem("watchtracker-media-artwork-full-color", String(selected)); } catch (_) { /* optional */ }
  if (selected) document.documentElement.dataset.mediaArtworkFullColor = "true";
  else delete document.documentElement.dataset.mediaArtworkFullColor;
  if ($("#media-artwork-full-color")) $("#media-artwork-full-color").checked = selected;
}

function applyEpisodeProgressPreference(enabled) {
  const selected = Boolean(enabled);
  state.showEpisodeProgress = selected;
  try { localStorage.setItem("watchtracker-show-episode-progress", String(selected)); } catch (_) { /* optional */ }
  if ($("#show-episode-progress")) $("#show-episode-progress").checked = selected;
}

function applyAccent(accent, customColor = undefined) {
  const valid = new Set(["forest", "ocean", "violet", "rose", "amber", "graphite"]);
  const selected = valid.has(accent) ? accent : "forest";
  const legacyColors = {forest: "#345b4c", ocean: "#315f86", violet: "#6a4b8a", rose: "#8b455d", amber: "#8a5a15", graphite: "#4f5e68"};
  const requested = customColor === undefined ? customAccentPreference() : customColor;
  const custom = typeof requested === "string" && /^#[0-9a-f]{6}$/i.test(requested) ? requested.toLowerCase() : legacyColors[selected];
  try {
    localStorage.setItem("watchtracker-accent", selected);
    localStorage.setItem("watchtracker-accent-custom", custom);
  } catch (_) { /* optional */ }
  document.documentElement.dataset.accent = selected;
  document.documentElement.dataset.customAccent = "true";
  document.documentElement.dataset.accentTone = colorTone(custom);
  document.documentElement.style.setProperty("--accent-choice", custom);
  // Set the visible palette directly as well as the source variable. Older
  // macOS WebKit builds can defer repainting dependent color-mix variables
  // until another appearance property changes.
  document.documentElement.style.setProperty("--accent", custom);
  document.documentElement.style.setProperty("--accent-hover", `color-mix(in srgb, ${custom} 82%, black)`);
  document.documentElement.style.setProperty("--accent-soft", `color-mix(in srgb, ${custom} 16%, var(--surface))`);
  document.documentElement.style.setProperty("--accent-2", `color-mix(in srgb, ${custom} 68%, #60758d)`);
  document.documentElement.style.setProperty("--accent-2-soft", `color-mix(in srgb, ${custom} 12%, var(--surface))`);
  document.documentElement.style.setProperty("--accent-ink", colorTone(custom) === "light" ? "#171a18" : "#ffffff");
  if ($("#accent-color")) $("#accent-color").value = custom;
  if (iconFollowAccentPreference()) applyIconPreference(undefined, undefined, true);
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
  syncNativeWindowBackground();
}

function queueAppearanceSave(payload, message, isCurrent = null) {
  state.appearanceSave = state.appearanceSave.catch(() => {}).then(async () => {
    if (isCurrent && !isCurrent()) return;
    const status = $("#appearance-state");
    if (status) {
      status.classList.add("pending");
      status.textContent = "Saving appearance…";
    }
    for (let attempt = 0; attempt < 2; attempt += 1) {
      if (isCurrent && !isCurrent()) return;
      try {
        await api("/api/settings/general", {method: "PUT", body: JSON.stringify(payload)});
        if (status) {
          status.classList.remove("pending");
          status.textContent = translatedText("Appearance changes save automatically.");
        }
        toast(message);
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
        toast("Appearance could not be saved. Change the option once more to retry.");
      }
    }
  });
  return state.appearanceSave;
}

async function saveThemePreference(preference) {
  applyTheme(preference);
  return queueAppearanceSave({theme: preference}, "Theme saved automatically.");
}

async function saveCustomAccentPreference(color) {
  applyAccent("forest", color);
  return queueAppearanceSave({accent: "forest", accent_color: color}, "Custom accent saved automatically.");
}

async function saveBackgroundPreference(color, strength = backgroundStrengthPreference(), mode = backgroundModePreference()) {
  applyBackgroundColor(color, strength, mode);
  return queueAppearanceSave(
    {background_color: color || null, background_strength: strength, background_mode: mode},
    color ? "Background appearance saved automatically." : "Default background restored."
  );
}

function applyBackgroundImage(data = state.backgroundImage) {
  state.backgroundImage = {
    available: Boolean(data.available ?? data.background_image_available),
    enabled: Boolean(data.enabled ?? data.background_image_enabled),
    opacity: Number(data.opacity ?? data.background_image_opacity ?? 24),
    tint: Boolean(data.tint ?? data.background_image_tint),
    version: data.version ?? data.background_image_version ?? null
  };
  const image = state.backgroundImage;
  const root = document.documentElement;
  if (image.available && image.enabled) {
    root.dataset.workspaceBackgroundImage = "true";
    root.style.setProperty("--workspace-background-image", `url("/api/settings/background-image?v=${encodeURIComponent(image.version || "current")}")`);
  } else {
    delete root.dataset.workspaceBackgroundImage;
    root.style.removeProperty("--workspace-background-image");
  }
  root.style.setProperty("--workspace-background-opacity", String(Math.max(0, Math.min(100, image.opacity)) / 100));
  if (image.tint) root.dataset.workspaceBackgroundTint = "true";
  else delete root.dataset.workspaceBackgroundTint;
  $("#background-image-controls").hidden = !image.available;
  $("#remove-background-image").hidden = !image.available;
  $("#background-image-enabled").checked = image.enabled;
  $("#background-image-opacity").value = String(image.opacity);
  $("#background-image-opacity-value").textContent = `${Math.round(image.opacity)}%`;
  $("#background-image-tint").checked = image.tint;
  $("#background-image-status").textContent = image.available
    ? "Stored on this device · excluded from backups and exports."
    : "No image selected.";
}

async function saveBackgroundImageOptions(overrides = {}) {
  const next = {...state.backgroundImage, ...overrides};
  applyBackgroundImage(next);
  await queueAppearanceSave({
    background_image_enabled: next.enabled,
    background_image_opacity: next.opacity,
    background_image_tint: next.tint
  }, "Workspace background saved automatically.");
}

async function uploadBackgroundImage(file) {
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    $("#background-image-status").textContent = "Validating and optimizing image…";
    const data = await api("/api/settings/background-image", {method: "PUT", body: form});
    applyBackgroundImage({...state.backgroundImage, ...data, enabled: true});
    toast("Workspace background imported");
  } catch (error) {
    applyBackgroundImage(state.backgroundImage);
    toast(error.message);
  } finally {
    $("#background-image-file").value = "";
  }
}

async function removeBackgroundImage() {
  if (!await confirmAction("Remove the workspace background image?", "The device-local image file will be deleted. Your background colour remains unchanged.", "Remove image")) return;
  try {
    await api("/api/settings/background-image", {method: "DELETE"});
    applyBackgroundImage({available: false, enabled: false, opacity: state.backgroundImage.opacity, tint: state.backgroundImage.tint, version: null});
    toast("Workspace background removed");
  } catch (error) { toast(error.message); }
}

async function saveMediaArtworkPreference(enabled) {
  applyMediaArtworkPreference(enabled);
  return queueAppearanceSave(
    {media_artwork_tint: Boolean(enabled)},
    enabled ? "Media artwork tint saved automatically." : "Media artwork tint turned off."
  );
}

async function saveMediaArtworkFullColorPreference(enabled) {
  applyMediaArtworkFullColorPreference(enabled);
  return queueAppearanceSave(
    {media_artwork_full_color: Boolean(enabled)},
    enabled ? "Full-colour artwork blend saved automatically." : "Full-colour artwork blend turned off."
  );
}

async function saveEpisodeProgressPreference(enabled) {
  applyEpisodeProgressPreference(enabled);
  const pending = queueAppearanceSave(
    {show_episode_progress: Boolean(enabled)},
    enabled ? "Episode counters shown on media tiles." : "Episode counters hidden from media tiles."
  );
  state.libraryLoaded = false;
  state.currentlyWatchingLoaded = false;
  if (state.view === "library") await loadLibrary({showSkeleton: false});
  else if (state.view === "currently_watching") await loadCurrentlyWatching();
  return pending;
}

async function saveIconPreference(backgroundColor, textColor, followAccent, revision) {
  if (revision !== state.iconPreferenceRevision) return state.appearanceSave;
  applyIconPreference(backgroundColor, textColor, followAccent);
  return queueAppearanceSave(
    {icon_background_color: backgroundColor, icon_text_color: textColor, icon_follow_accent: Boolean(followAccent)},
    "App icon colours saved automatically.",
    () => revision === state.iconPreferenceRevision
  );
}

function scheduleIconPreferenceSave(backgroundColor, textColor, followAccent, delay = 0) {
  const background = backgroundColor || DEFAULT_ICON_BACKGROUND;
  const text = textColor || DEFAULT_ICON_TEXT;
  const followsAccent = Boolean(followAccent);
  applyIconPreference(background, text, followsAccent);
  state.iconPreferenceRevision += 1;
  const revision = state.iconPreferenceRevision;
  clearTimeout(state.iconSaveTimer);
  state.iconSaveTimer = setTimeout(() => {
    if (revision !== state.iconPreferenceRevision) return;
    saveIconPreference(background, text, followsAccent, revision);
  }, delay);
}

function switchView(view, {persist = true, push = false, scrollTop = false} = {}) {
  const dedicatedServerAccount = state.currentUser?.role === "admin" && !state.currentUser?.legacy_personal_library;
  if (dedicatedServerAccount && state.serverConsoleAvailable) view = "server_console";
  state.view = validViews.has(view) ? view : "library";
  view = state.view;
  const active = $(`#${view.replaceAll("_", "-")}-view`);
  $$(".app-view").forEach(section => { section.hidden = section !== active; });
  active.classList.remove("view-enter");
  requestAnimationFrame(() => active.classList.add("view-enter"));
  $$(".nav-button, #server-console-nav").forEach(button => {
    const selected = button.dataset.view === view || (view === "list_detail" && button.dataset.listNav === state.activeListId);
    button.classList.toggle("active", selected);
    if (selected) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  const showActiveSubnav = view === "active_shows" || view === "calendar";
  $(".nav-subview").hidden = !showActiveSubnav;
  const activeShowsNav = $('.nav-button[data-view="active_shows"]');
  if (activeShowsNav) activeShowsNav.classList.toggle("parent-active", view === "calendar");
  if (persist) persistNavigationState({push});
  if (view === "insights") loadInsights();
  else if (view === "currently_watching" && !state.currentlyWatchingLoaded) loadCurrentlyWatching();
  else if (view === "active_shows" && !state.activeShowsLoaded) loadActiveShows();
  else if (view === "calendar" && !state.calendarLoaded) loadReleaseCalendar();
  else if (view === "rankings" && !state.rankingsLoaded) loadRankings();
  else if (view === "lists" && !state.listsLoaded) loadLists();
  else if (view === "notifications") loadListNotifications();
  else if (view === "list_detail" && state.activeListId) loadListDetail(state.activeListId);
  else if (view === "library" && !state.libraryLoaded && !state.libraryLoading) loadLibrary();
  if (scrollTop) requestAnimationFrame(() => {
    active.querySelector("h2")?.focus({preventScroll: true});
    window.scrollTo({top: 0, behavior: "auto"});
  });
}

function focusQuickAdd() {
  const dialog = $("#quick-add-dialog");
  showMessage($("#search-state"), "");
  $("#duplicate-actions").hidden = true;
  if ($("#quick-add-details-dialog").open) $("#quick-add-details-dialog").close();
  openDialog(dialog);
  setTimeout(() => $("#search-input").focus(), 80);
}

function openImportFromSettings() {
  state.importReturnToSettings = true;
  if ($("#settings-dialog").open) $("#settings-dialog").close();
  openDialog($("#import-dialog"));
}

function scrollDocumentTop() {
  clearTimeout(scrollDocumentTop.restoreTimer);
  document.documentElement.style.scrollBehavior = "auto";
  document.documentElement.scrollTop = 0;
  document.body.scrollTop = 0;
  window.scrollTo(0, 0);
  scrollDocumentTop.restoreTimer = setTimeout(() => document.documentElement.style.removeProperty("scroll-behavior"), 20);
}

function quickOptions() {
  const value = selector => $(selector).value || null;
  const status = value("#quick-status") || "watched";
  return {
    status,
    personal_rating: value("#quick-rating") ? Number(value("#quick-rating")) : null,
    started_date: value("#quick-started"),
    finished_date: value("#quick-finished"),
    user_tags: listValue(value("#quick-tags")),
    notes: value("#quick-notes")
  };
}

function updateQuickRefineAvailability() {
  const button = $("#quick-confirm-refine");
  button.hidden = !state.advancedRatingsEnabled;
  const hasRating = Boolean($("#quick-rating").value);
  button.disabled = !hasRating;
  button.title = hasRating ? "" : interfaceCopy("Add a personal rating first", "Ajoutez d’abord une note personnelle");
}

function openQuickAddDetails(result) {
  state.selectedResult = result;
  $("#quick-add-details-heading").textContent = `${result.title}${result.year ? ` (${result.year})` : ""}`;
  $("#quick-add-preview").innerHTML = `${imageHtml(result.poster_url, result.title, "poster", interfaceCopy(`Poster for ${result.title}`, `Affiche de ${result.title}`))}<div><p class="entry-meta">${esc(result.year || translatedText("Year unknown"))} · ${esc(mediaLabel(result.media_type))}</p>${result.overview ? `<p translate="no">${esc(result.overview)}</p>` : `<p class="muted">${esc(interfaceCopy("No provider summary is available.", "Aucun résumé du fournisseur n’est disponible."))}</p>`}</div>`;
  $("#quick-add-preview").style.setProperty("--media-hue", titleHue(result.title));
  ["#quick-rating", "#quick-started", "#quick-finished", "#quick-tags", "#quick-notes"].forEach(selector => { $(selector).value = ""; });
  $("#quick-status").value = "watched";
  showMessage($("#quick-add-details-message"), "");
  updateQuickRefineAvailability();
  bindPosterFallbacks($("#quick-add-preview"));
  if ($("#quick-add-dialog").open) $("#quick-add-dialog").close();
  openDialog($("#quick-add-details-dialog"));
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
      openQuickAddDetails(data.results[Number(button.dataset.index)]);
    }));
    bindPosterFallbacks(results);
  } catch (error) {
    if (error.name !== "AbortError") showMessage($("#search-state"), `${error.message} You can still add manually.`, true);
  }
}

async function addSearchResult(result, ifExisting = "return_existing", {refine = false} = {}) {
  state.selectedResult = result;
  showMessage($("#quick-add-details-message"), `Adding ${result.title}…`);
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
      if ($("#quick-add-details-dialog").open) $("#quick-add-details-dialog").close();
      openDialog($("#quick-add-dialog"));
      return;
    }
    $("#duplicate-actions").hidden = true;
    showMessage($("#search-state"), "");
    toast(data.action === "rewatched" ? "Rewatch recorded" : `${result.title} saved`);
    state.page = 1;
    if ($("#quick-add-details-dialog").open) $("#quick-add-details-dialog").close();
    if ($("#quick-add-dialog").open) $("#quick-add-dialog").close();
    $("#search-input").value = "";
    $("#search-results").innerHTML = "";
    $("#quick-add-panel").classList.remove("has-results");
    state.currentlyWatchingLoaded = false;
    state.activeShowsLoaded = false;
    state.calendarLoaded = false;
    state.rankingsLoaded = false;
    state.listsLoaded = false;
    await loadLibrary({focusEntryId: state.view === "library" ? data.entry.id : null});
    if (state.view === "currently_watching") await loadCurrentlyWatching();
    if (state.view === "active_shows") await loadActiveShows();
    if (state.view === "calendar") await loadReleaseCalendar();
    if (state.view === "rankings") await loadRankings();
    if (state.view === "lists") await loadLists();
    if (state.view === "insights") await loadInsights();
    if (refine) await startSingleTitleRefinement(data.entry.id);
  } catch (error) { showMessage($("#quick-add-details-message"), error.message, true); }
}

function libraryParams() {
  const params = new URLSearchParams({page: state.page, page_size: state.pageSize, sort: state.sort, direction: state.direction});
  Object.entries(state.filters).forEach(([key, value]) => { if (value !== "" && value !== false) params.set(key, value); });
  return params;
}

function entryPoster(item) {
  return item.poster_override_url || item.poster_url;
}

function episodeProgressHtml(entry) {
  if (!state.showEpisodeProgress) return "";
  const progress = entry.episode_progress;
  if (!progress || !progress.total) return "";
  const watched = Math.min(Math.max(Number(progress.watched || 0), 0), Number(progress.total));
  const total = Number(progress.total);
  return `<span class="card-episode-progress" data-episode-progress data-watched="${watched}" data-total="${total}" aria-label="${esc(interfaceCopy(`${watched} of ${total} episodes watched`, `${watched} épisodes vus sur ${total}`))}"><button type="button" class="episode-progress-step" data-episode-step="-1" aria-label="${esc(translatedText("Decrease watched episode count"))}" ${watched <= 0 ? "disabled" : ""}>−</button><span><strong>${watched}</strong> / ${total} <small>${esc(translatedText("episodes"))}</small></span><button type="button" class="episode-progress-step" data-episode-step="1" aria-label="${esc(translatedText("Increase watched episode count"))}" ${watched >= total ? "disabled" : ""}>+</button></span>`;
}

function cardHtml(entry) {
  const item = entry.catalog_item;
  const title = item.canonical_title;
  const posterUrl = entryPoster(item);
  const poster = imageHtml(posterUrl, title, "poster", interfaceCopy(`Poster for ${title}`, `Affiche de ${title}`));
  const genres = [...new Set(entry.effective_genres || [])];
  const subgenres = [...new Set(entry.effective_subgenres || [])].filter(value => !genres.includes(value));
  const signals = [...genres.slice(0, 2), ...subgenres].slice(0, 2);
  const verifiedIdentity = Boolean(item.tmdb_movie_id || item.tmdb_tv_id || item.anilist_id || item.mal_id || Object.keys(item.external_ids || {}).length);
  const incomplete = !posterUrl || !item.release_year || !verifiedIdentity;
  const mediaArtwork = safeImageUrl(posterUrl);
  return `<article class="entry-card status-${esc(entry.status)} media-${esc(item.media_type)} ${entry.deleted_at ? "deleted" : ""}" data-entry="${entry.id}" data-media-hue="${titleHue(title)}"${mediaArtwork ? ` data-media-art="${esc(mediaArtwork)}"` : ""} style="--media-hue:${titleHue(title)}">
    ${poster}<div class="entry-copy"><h3 translate="no">${esc(title)}</h3><p class="entry-meta">${esc(item.release_year || translatedText("Year unknown"))} · ${esc(translatedText(mediaLabel(item.media_type)))}${item.provider_format && item.provider_format !== item.media_type ? ` · ${esc(providerFormatLabel(item.provider_format))}` : ""}</p></div>
    <div class="entry-signals"><span class="chip status-chip">${esc(translatedText(statusLabel(entry.status)))}</span>${signals.map(signal => `<span class="chip genre-chip" translate="no">${esc(signal)}</span>`).join("")}${incomplete ? `<span class="chip warning-chip">⚠ ${esc(translatedText("Metadata"))}</span>` : ""}</div>
    <div class="entry-actions"><span class="chip view-chip">${esc(countText(entry.view_count, "view", "views", "visionnage", "visionnages"))}</span><button type="button" class="favorite-toggle ${entry.is_favorite ? "active" : ""}" data-favorite-toggle aria-pressed="${entry.is_favorite}" aria-label="${esc(translatedText(entry.is_favorite ? `Remove ${title} from favorites` : `Add ${title} to favorites`))}" title="${esc(translatedText(entry.is_favorite ? "Remove favorite" : "Add favorite"))}"><svg aria-hidden="true"><use href="#icon-heart"></use></svg></button>${episodeProgressHtml(entry)}<button type="button" class="quiet media-info-button" data-details aria-label="${esc(interfaceCopy(`Information about ${title}`, `Informations sur ${title}`))}" title="${esc(interfaceCopy("More information", "Plus d’informations"))}"><svg aria-hidden="true"><use href="#icon-info"></use></svg></button></div>
  </article>`;
}

function bindPosterFallbacks(root = document) {
  $$('[data-media-art]', root).forEach(card => {
    const artwork = safeImageUrl(card.dataset.mediaArt);
    if (artwork) card.style.setProperty("--media-art", `url(${JSON.stringify(artwork)})`);
  });
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
    $("#library-updated").textContent = `${translatedText("Updated")} ${new Date().toLocaleTimeString(interfaceLocale(), {hour: "2-digit", minute: "2-digit"})}`;
    persistNavigationState();
    const titleWord = state.interfaceLanguage === "fr" ? (data.total === 1 ? "titre" : "titres") : (data.total === 1 ? "title" : "titles");
    $("#library-count").innerHTML = `<strong>${esc(formatInteger(data.total))}</strong> <span>${esc(titleWord)}</span>`;
    container.innerHTML = data.items.length ? data.items.map(cardHtml).join("") : `<div class="empty-state"><span class="empty-monogram" aria-hidden="true">PMT</span><h3>Nothing here yet — let’s fix that</h3><p>Build your library one title at a time, or bring an existing media log.</p><div class="empty-actions"><button data-empty-search>Search a title</button><button data-empty-import class="quiet">Import a media log</button></div></div>`;
    showMessage($("#library-state"), "");
    bindCards();
    renderPagination(data.page, data.pages, data.total);
    if (preserveScroll) requestAnimationFrame(() => window.scrollTo({top: scrollPosition}));
    if (focusEntryId) requestAnimationFrame(() => $$(".entry-card").find(card => card.dataset.entry === focusEntryId)?.querySelector("[data-details]")?.focus({preventScroll: true}));
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

function bindCards(root = $("#library"), reload = () => loadLibrary({preserveScroll: true, showSkeleton: false})) {
  bindPosterFallbacks(root);
  $$(".entry-card", root).forEach(card => {
    if (card.dataset.mediaArt) card.style.setProperty("--media-art", `url(${JSON.stringify(card.dataset.mediaArt)})`);
    const id = card.dataset.entry;
    $("[data-details]", card)?.addEventListener("click", () => openEntry(id));
    $$('[data-episode-step]', card).forEach(button => button.addEventListener("click", async event => {
      const progress = event.currentTarget.closest("[data-episode-progress]");
      const watched = Number(progress.dataset.watched || 0);
      const total = Number(progress.dataset.total || 0);
      const next = Math.min(Math.max(watched + Number(event.currentTarget.dataset.episodeStep), 0), total);
      if (next === watched) return;
      $$('button', progress).forEach(control => { control.disabled = true; });
      try {
        await api(`/api/entries/${id}`, {method: "PATCH", body: JSON.stringify({episode_progress_count: next})});
        state.currentlyWatchingLoaded = false;
        state.activeShowsLoaded = false;
        state.rankingsLoaded = false;
        state.listsLoaded = false;
        await reload();
      } catch (error) {
        toast(error.message);
        $$('button', progress).forEach(control => { control.disabled = false; });
      }
    }));
    $("[data-favorite-toggle]", card)?.addEventListener("click", async event => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        await api(`/api/entries/${id}`, {method: "PATCH", body: JSON.stringify({is_favorite: button.getAttribute("aria-pressed") !== "true"})});
        state.listsLoaded = false;
        state.rankingsLoaded = false;
        await reload();
      } catch (error) { toast(error.message); }
      finally { button.disabled = false; }
    });
  });
  $("[data-empty-search]", root)?.addEventListener("click", focusQuickAdd);
  $("[data-empty-import]", root)?.addEventListener("click", () => openDialog($("#import-dialog")));
}

async function loadAllActiveEntries() {
  const first = await api("/api/entries?page=1&page_size=100&sort=title&direction=asc");
  const responses = await Promise.all(
    Array.from({length: Math.max(0, first.pages - 1)}, (_, index) =>
      api(`/api/entries?page=${index + 2}&page_size=100&sort=title&direction=asc`)
    )
  );
  return [first, ...responses].flatMap(page => page.items);
}

function renderMediaLists(lists) {
  const container = $("#media-lists");
  if (!lists.length) {
    container.innerHTML = state.listScope === "shared"
      ? `<div class="empty-state"><span class="empty-monogram" aria-hidden="true">PMT</span><h3>${esc(translatedText("No shared lists yet"))}</h3><p>${esc(translatedText("Import a PMT shared-list file here. It never imports another person’s ratings, notes, or history."))}</p></div>`
      : `<div class="empty-state"><span class="empty-monogram" aria-hidden="true">PMT</span><h3>${esc(translatedText("Create your first list"))}</h3><p>${esc(translatedText("Use a list for a watch night, a theme, or anything else you want to group."))}</p></div>`;
    return;
  }
  container.innerHTML = lists.map(mediaList => {
    const date = new Date(mediaList.created_at).toLocaleDateString(interfaceLocale(), {year: "numeric", month: "short", day: "numeric"});
    const ownership = mediaList.current_user_role === "owner" ? "" : ` · ${mediaList.current_user_role}`;
    const origin = mediaList.source_kind === "portable" ? mediaList.source_label : null;
    return `<button type="button" class="media-list-summary" data-open-list="${mediaList.id}"><span><small>${origin ? `${esc(origin)} · ` : ""}${esc(translatedText(mediaList.pinned_to_navigation ? "Pinned to navigation" : `Created ${date}`))}${esc(ownership)}</small><strong translate="no">${esc(mediaList.name)}</strong></span><span class="media-list-summary-tail">${state.listScope === "shared" || mediaList.visibility === "shared" ? `<span class="chip">${esc(translatedText("Shared"))}</span>` : ""}<span class="chip">${countText(mediaList.items.length, "title", "titles", "titre", "titres")}</span><svg aria-hidden="true"><use href="#icon-chevron"></use></svg></span></button>`;
  }).join("");
  $$('[data-open-list]', container).forEach(button => button.addEventListener("click", () => openList(button.dataset.openList)));
}

function renderPinnedListNavigation(lists) {
  const container = $("#custom-list-navigation");
  if (!container) return;
  const pinned = lists.filter(mediaList => mediaList.pinned_to_navigation).slice(0, 5);
  container.innerHTML = pinned.map(mediaList => `<button type="button" class="nav-button custom-list-nav-button" data-view="list_detail" data-list-nav="${mediaList.id}" title="${esc(mediaList.name)}"><svg aria-hidden="true"><use href="#icon-list"></use></svg><span class="nav-label" translate="no">${esc(mediaList.name)}</span></button>`).join("");
  $$("[data-list-nav]", container).forEach(button => button.addEventListener("click", () => openList(button.dataset.listNav)));
}

function openList(listId) {
  state.activeListId = listId;
  state.activeList = null;
  switchView("list_detail", {push: true, scrollTop: true});
}

async function loadLists() {
  const container = $("#media-lists");
  container.setAttribute("aria-busy", "true");
  showMessage($("#lists-state"), "Loading lists…");
  try {
    const lists = await api(`/api/lists?sort=${encodeURIComponent(state.listSort)}&direction=${state.listSortDirection}`);
    state.listsLoaded = true;
    const visible = lists.filter(mediaList => state.listScope === "own"
      ? mediaList.source_kind !== "portable" && mediaList.current_user_role === "owner"
      : mediaList.source_kind === "portable" || mediaList.current_user_role !== "owner");
    $$("[data-list-scope]").forEach(button => {
      const active = button.dataset.listScope === state.listScope;
      button.setAttribute("aria-pressed", String(active));
      button.classList.toggle("active", active);
    });
    $("#owned-list-actions").hidden = state.listScope !== "own";
    $("#import-shared-list-form").hidden = state.listScope !== "shared";
    $("#lists-eyebrow").textContent = translatedText(state.listScope === "shared" ? "Shared collections" : "Your own collections");
    $("#lists-hint").textContent = translatedText(state.listScope === "shared"
      ? "Shared lists are portable snapshots or lists another server user shared with you. Importing one never changes your Library."
      : "Lists organize titles already in your Library. Removing a title from a list never deletes it from PMT.");
    renderMediaLists(visible);
    renderPinnedListNavigation(lists);
    await loadListNotifications();
    showMessage($("#lists-state"), "");
  } catch (error) {
    state.listsLoaded = false;
    container.innerHTML = "";
    showMessage($("#lists-state"), error.message, true);
  } finally { container.setAttribute("aria-busy", "false"); }
}

async function loadListNotifications() {
  const [releaseResult, listResult] = await Promise.allSettled([
    api("/api/releases/notifications"),
    api("/api/v1/notifications?limit=50")
  ]);
  const releases = releaseResult.status === "fulfilled" ? releaseResult.value : {items: [], unread: 0};
  const lists = listResult.status === "fulfilled" ? listResult.value : {items: [], unread: 0};
  const unread = Number(releases.unread || 0) + Number(lists.unread || 0);
  $("#navigation-notification-count").textContent = String(unread);
  $("#navigation-notification-count").hidden = unread === 0;
  $("#release-notification-count").textContent = String((releases.items || []).length);
  $("#list-notification-count").textContent = String((lists.items || []).length);
  $("#release-notifications").innerHTML = (releases.items || []).length
    ? releases.items.map(item => {
      const labels = {
        episode_announced: "Episode announced",
        episode_released: "Episode released",
        season_announced: "Season announced",
        schedule_changed: "Schedule changed"
      };
      const label = translatedText(labels[item.event_type] || "Release update");
      const when = item.effective_date ? formatDate(item.effective_date) : translatedText("Date not announced");
      return `<article class="integration-card ${item.read ? "" : "notification-unread"}"><div><strong translate="no">${esc(item.title)}</strong><p>${esc(label)} · ${esc(when)}</p><p class="muted">${esc(new Date(item.first_seen_at).toLocaleString(interfaceLocale()))}</p></div><div class="metadata-actions"><button type="button" class="quiet" data-open-release-entry="${esc(item.entry_id)}">Open title</button>${!item.read ? `<button type="button" class="quiet" data-release-notification-action="read" data-release-notification-id="${esc(item.id)}">Mark read</button>` : ""}<button type="button" class="quiet-danger" data-release-notification-action="dismiss" data-release-notification-id="${esc(item.id)}">Dismiss</button></div></article>`;
    }).join("")
    : `<p class="muted">No release notifications yet. Follow a series or run a library check to cache upcoming dates.</p>`;
  $("#list-notifications").innerHTML = (lists.items || []).length ? lists.items.map(item => `<article class="integration-card ${item.read_at ? "" : "notification-unread"}"><div><strong>${esc(item.title)}</strong><p>${esc(item.message)}</p><p class="muted">${esc(new Date(item.created_at).toLocaleString(interfaceLocale()))}</p></div><div class="metadata-actions">${item.resource_type === "media_list" ? `<button type="button" class="quiet" data-open-notification-list="${esc(item.resource_id)}">Open list</button>` : ""}${!item.read_at ? `<button type="button" class="quiet" data-notification-action="read" data-notification-id="${esc(item.id)}">Mark read</button>` : ""}<button type="button" class="quiet-danger" data-notification-action="dismiss" data-notification-id="${esc(item.id)}">Dismiss</button></div></article>`).join("") : `<p class="muted">No shared-list notifications.</p>`;
  $("#collaboration-notification-section").hidden = state.accessMode === "local" && !(lists.items || []).length;
  const failures = [releaseResult, listResult].filter(result => result.status === "rejected");
  showMessage($("#notifications-state"), failures.length === 2 ? failures[0].reason.message : "", failures.length === 2);
}

async function manageReleaseNotification(event) {
  const open = event.target.closest("[data-open-release-entry]");
  if (open) {
    switchView("library", {push: true, scrollTop: true});
    await openEntry(open.dataset.openReleaseEntry, "releases");
    return;
  }
  const button = event.target.closest("[data-release-notification-action]");
  if (!button) return;
  try {
    await api(`/api/releases/notifications/${button.dataset.releaseNotificationId}`, {
      method: "PATCH",
      body: JSON.stringify({action: button.dataset.releaseNotificationAction})
    });
    await loadListNotifications();
  } catch (error) { showMessage($("#notifications-state"), error.message, true); }
}

async function manageListNotification(event) {
  const open = event.target.closest("[data-open-notification-list]");
  if (open) return openList(open.dataset.openNotificationList);
  const button = event.target.closest("[data-notification-action]");
  if (!button) return;
  try {
    await api(`/api/v1/notifications/${button.dataset.notificationId}`, {method: "PATCH", body: JSON.stringify({action: button.dataset.notificationAction})});
    await loadListNotifications();
  } catch (error) { showMessage($("#notifications-state"), error.message, true); }
}

async function loadListNavigation() {
  try {
    const lists = await api("/api/lists?sort=name&direction=asc");
    renderPinnedListNavigation(lists);
  } catch (_) { /* Custom navigation is optional; the Lists page remains available. */ }
}

function listEntryLabel(entry) {
  const catalog = entry.catalog_item;
  return `${catalog.canonical_title}${catalog.release_year ? ` (${catalog.release_year})` : ""} · ${mediaLabel(catalog.media_type)}`;
}

function closeListTitleOptions() {
  const input = $("#list-detail-title-search");
  const options = $("#list-detail-title-options");
  if (!input || !options) return;
  options.hidden = true;
  input.setAttribute("aria-expanded", "false");
  input.removeAttribute("aria-activedescendant");
  state.listPickerIndex = -1;
}

function selectListTitle(entry) {
  const input = $("#list-detail-title-search");
  const hidden = $("#list-detail-add-form [name='entry_id']");
  input.value = listEntryLabel(entry);
  hidden.value = entry.id;
  $("#list-detail-add-form button[type='submit']").disabled = false;
  closeListTitleOptions();
}

function renderListTitleOptions(query = "", {open = true} = {}) {
  const input = $("#list-detail-title-search");
  const hidden = $("#list-detail-add-form [name='entry_id']");
  const options = $("#list-detail-title-options");
  if (!input || !hidden || !options) return;
  const normalized = query.trim().toLocaleLowerCase(interfaceLocale());
  const matches = state.listAvailableEntries.filter(entry => {
    const catalog = entry.catalog_item;
    return [catalog.canonical_title, catalog.original_title, catalog.release_year]
      .filter(Boolean)
      .some(value => String(value).toLocaleLowerCase(interfaceLocale()).includes(normalized));
  }).slice(0, 10);
  state.listPickerIndex = -1;
  input.removeAttribute("aria-activedescendant");
  options.innerHTML = matches.length
    ? matches.map((entry, index) => `<button id="list-title-option-${index}" type="button" role="option" aria-selected="false" data-list-title-option="${entry.id}"><span translate="no">${esc(entry.catalog_item.canonical_title)}</span><small>${entry.catalog_item.release_year || "Year unknown"} · ${esc(mediaLabel(entry.catalog_item.media_type))}</small></button>`).join("")
    : `<p class="muted">${state.listAvailableEntries.length ? "No matching Library titles" : "No more Library titles"}</p>`;
  $$('[data-list-title-option]', options).forEach(button => button.addEventListener("click", () => {
    const entry = state.listAvailableEntries.find(item => item.id === button.dataset.listTitleOption);
    if (entry) selectListTitle(entry);
  }));
  options.hidden = !open;
  input.setAttribute("aria-expanded", String(open));
}

function moveListTitlePicker(direction) {
  const input = $("#list-detail-title-search");
  const buttons = $$('[data-list-title-option]', $("#list-detail-title-options"));
  if (!buttons.length) return;
  state.listPickerIndex = (state.listPickerIndex + direction + buttons.length) % buttons.length;
  buttons.forEach((button, index) => button.setAttribute("aria-selected", String(index === state.listPickerIndex)));
  const active = buttons[state.listPickerIndex];
  input.setAttribute("aria-activedescendant", active.id);
  active.scrollIntoView({block: "nearest"});
}

async function loadListDetail(listId) {
  const container = $("#list-detail-library");
  container.setAttribute("aria-busy", "true");
  container.innerHTML = librarySkeletons();
  showMessage($("#list-detail-state"), "Loading list…");
  try {
    const [mediaList, entries] = await Promise.all([api(`/api/lists/${listId}`), loadAllActiveEntries()]);
    if (state.activeListId !== listId) return;
    state.activeList = mediaList;
    state.listLibraryEntries = entries;
    $("#list-detail-heading").textContent = mediaList.name;
    $("#list-detail-count").textContent = countText(mediaList.items.length, "title", "titles", "titre", "titres");
    $("#toggle-list-navigation").textContent = mediaList.pinned_to_navigation ? "Remove from navigation" : "Add to navigation";
    $("#toggle-list-navigation").setAttribute("aria-pressed", String(mediaList.pinned_to_navigation));
    $("#toggle-list-navigation").hidden = mediaList.current_user_role !== "owner" || mediaList.source_kind === "portable";
    $("#delete-current-list").hidden = mediaList.current_user_role !== "owner" && mediaList.source_kind !== "portable";
    $("#delete-current-list").textContent = translatedText(mediaList.source_kind === "portable" ? "Remove shared list" : "Delete list");
    const exportLink = $("#export-current-list");
    exportLink.hidden = mediaList.source_kind === "portable";
    exportLink.href = `/api/exports/lists/${encodeURIComponent(mediaList.id)}.pmt-list.json`;
    $("#list-detail-add-form").hidden = !mediaList.can_edit;
    $("#list-sharing-chip").textContent = mediaList.visibility === "shared" ? `${mediaList.members.length} members` : "Private";
    $("#share-list-form").hidden = !mediaList.can_manage_members;
    $("#list-sharing-panel").hidden = mediaList.source_kind === "portable";
    renderListMembers(mediaList);
    const included = new Set(mediaList.items.map(item => item.catalog_item.id));
    const available = entries.filter(entry => !included.has(entry.catalog_item.id));
    state.listAvailableEntries = available;
    $("#list-detail-title-search").value = "";
    $("#list-detail-title-search").disabled = !available.length;
    $("#list-detail-title-search").placeholder = available.length ? "Search Library titles…" : "No more Library titles";
    $("#list-detail-add-form [name='entry_id']").value = "";
    $("#list-detail-add-form button[type='submit']").disabled = true;
    renderListTitleOptions("", {open: false});
    container.innerHTML = mediaList.items.length ? mediaList.items.map(item => sharedListItemHtml(item, mediaList.can_edit)).join("") : `<div class="empty-state"><h3>This list is empty</h3><p>${mediaList.can_edit ? "Add an existing Library title using the control above." : "An editor has not added any titles yet."}</p></div>`;
    bindCards(container, () => loadListDetail(listId));
    $$('[data-remove-current-list-item]', container).forEach(button => button.addEventListener("click", async () => {
      try {
        await api(`/api/v1/lists/${listId}/items/${button.dataset.removeCurrentListItem}`, {method: "DELETE"});
        state.listsLoaded = false;
        await loadListDetail(listId);
      } catch (error) { toast(error.message); }
    }));
    $$('[data-add-shared-title]', container).forEach(button => button.addEventListener("click", async () => {
      try {
        await api(`/api/v1/catalog/${button.dataset.addSharedTitle}/library`, {method: "POST", body: "{}"});
        state.libraryLoaded = false;
        await loadListDetail(listId);
        toast("Added to your library");
      } catch (error) { toast(error.message); }
    }));
    if (mediaList.source_kind !== "portable") await loadListActivity(listId);
    showMessage($("#list-detail-state"), "");
  } catch (error) {
    container.innerHTML = "";
    showMessage($("#list-detail-state"), error.message, true);
  } finally { container.setAttribute("aria-busy", "false"); }
}

function sharedListItemHtml(item, canEdit) {
  const catalog = item.catalog_item;
  const remove = canEdit ? `<button type="button" class="quiet-danger list-remove-button" data-remove-current-list-item="${esc(catalog.id)}">Remove from list</button>` : "";
  if (item.entry) return `<div class="list-detail-tile" data-list-entry="${esc(item.entry.id)}">${cardHtml(item.entry)}${item.shared_note ? `<p class="muted shared-list-note">${esc(item.shared_note)}</p>` : ""}${remove}</div>`;
  const title = catalog.canonical_title;
  const poster = imageHtml(catalog.poster_url, title, "poster", `Poster for ${title}`);
  return `<div class="list-detail-tile"><article class="entry-card shared-catalog-card media-${esc(catalog.media_type)}" data-media-hue="${titleHue(title)}" style="--media-hue:${titleHue(title)}">${poster}<div class="entry-copy"><h3 translate="no">${esc(title)}</h3><p class="entry-meta">${esc(catalog.release_year || "Year unknown")} · ${esc(mediaLabel(catalog.media_type))}</p></div><div class="entry-signals"><span class="chip">Not in your library</span></div><div class="entry-actions"><button type="button" data-add-shared-title="${esc(catalog.id)}">Add to my library</button></div></article>${item.shared_note ? `<p class="muted shared-list-note">${esc(item.shared_note)}</p>` : ""}${remove}</div>`;
}

function renderListMembers(mediaList) {
  $("#list-members").innerHTML = (mediaList.members || []).map(member => `<article class="integration-card"><div><strong>${esc(member.display_name)}</strong><p class="muted">@${esc(member.username)} · ${esc(member.role)}</p></div>${mediaList.can_manage_members && member.role !== "owner" ? `<div class="metadata-actions"><select data-list-member-role="${esc(member.user_id)}" aria-label="Permission for ${esc(member.display_name)}"><option value="viewer" ${member.role === "viewer" ? "selected" : ""}>Viewer</option><option value="editor" ${member.role === "editor" ? "selected" : ""}>Editor</option></select><button type="button" class="quiet-danger" data-remove-list-member="${esc(member.user_id)}">Remove</button></div>` : `<span class="chip">${esc(member.role)}</span>`}</article>`).join("");
}

async function loadListActivity(listId = state.activeListId) {
  if (!listId) return;
  try {
    const data = await api(`/api/v1/lists/${listId}/activity?limit=20`);
    $("#list-activity").innerHTML = (data.items || []).length ? data.items.map(item => `<article class="integration-card"><div><strong>${esc(String(item.action).replaceAll("_", " "))}</strong><p class="muted">${esc(item.actor_display_name || "Former member")} · ${esc(new Date(item.created_at).toLocaleString(interfaceLocale()))}</p></div></article>`).join("") : `<p class="muted">No collaboration activity yet.</p>`;
  } catch (error) { $("#list-activity").innerHTML = `<p class="error">${esc(error.message)}</p>`; }
}

async function shareActiveList(event) {
  event.preventDefault();
  if (!state.activeListId) return;
  const values = Object.fromEntries(new FormData(event.currentTarget));
  try {
    const mediaList = await api(`/api/v1/lists/${state.activeListId}/members`, {method: "POST", body: JSON.stringify(values)});
    state.activeList = mediaList;
    event.currentTarget.reset();
    await loadListDetail(state.activeListId);
    toast("List shared");
  } catch (error) { showMessage($("#list-detail-state"), error.message, true); }
}

async function importSharedList(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  showMessage($("#lists-state"), translatedText("Checking shared-list file…"));
  try {
    const result = await api("/api/lists/import", {method: "POST", body: new FormData(form)});
    form.reset();
    state.listsLoaded = false;
    state.listScope = "shared";
    await loadLists();
    toast(translatedText(result.imported ? "Shared list imported" : "This shared list was already imported"));
  } catch (error) {
    showMessage($("#lists-state"), error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function manageActiveListMember(event) {
  if (!state.activeListId) return;
  const role = event.target.closest("[data-list-member-role]");
  const remove = event.target.closest("[data-remove-list-member]");
  if (!role && !remove) return;
  if (role && event.type !== "change") return;
  const userId = role?.dataset.listMemberRole || remove?.dataset.removeListMember;
  try {
    if (role) await api(`/api/v1/lists/${state.activeListId}/members/${userId}`, {method: "PATCH", body: JSON.stringify({role: role.value})});
    else await api(`/api/v1/lists/${state.activeListId}/members/${userId}`, {method: "DELETE"});
    await loadListDetail(state.activeListId);
  } catch (error) { showMessage($("#list-detail-state"), error.message, true); }
}

async function loadCurrentlyWatching() {
  const container = $("#currently-watching-library");
  container.setAttribute("aria-busy", "true");
  container.innerHTML = librarySkeletons();
  $("#watching-scope").value = state.watchingScope;
  const scopeLabels = {all: "active or planned", watching: "currently watching", rewatching: "rewatching", planned: "planned"};
  showMessage($("#currently-watching-state"), `Loading ${scopeLabels[state.watchingScope]} titles…`);
  try {
    const statuses = state.watchingScope === "all" ? ["watching", "rewatching", "plan_to_watch"] : [state.watchingScope === "planned" ? "plan_to_watch" : state.watchingScope];
    const responses = await Promise.all(statuses.map(status => api(`/api/entries?status=${status}&sort=recently_watched&direction=desc&page_size=96`)));
    const items = [...new Map(responses.flatMap(data => data.items).map(item => [item.id, item])).values()].sort((left, right) => String(right.watched_date || right.updated_at).localeCompare(String(left.watched_date || left.updated_at)));
    state.currentlyWatchingLoaded = true;
    container.innerHTML = items.length ? items.map(cardHtml).join("") : `<div class="empty-state"><span class="empty-monogram" aria-hidden="true">PMT</span><h3>No ${esc(scopeLabels[state.watchingScope])} titles</h3><p>Change a title’s status in Library details and it will appear here.</p><div class="empty-actions"><button data-empty-search>Quick Add</button></div></div>`;
    showMessage($("#currently-watching-state"), items.length ? countText(items.length, "title", "titles", "titre", "titres") : "");
    bindCards(container);
  } catch (error) {
    container.innerHTML = "";
    showMessage($("#currently-watching-state"), error.message, true);
  } finally { container.setAttribute("aria-busy", "false"); }
}

async function loadActiveShows() {
  const container = $("#active-shows-library");
  container.setAttribute("aria-busy", "true");
  container.innerHTML = librarySkeletons();
  showMessage($("#active-shows-state"), state.interfaceLanguage === "fr" ? "Chargement des séries avec de nouveaux épisodes annoncés…" : "Loading shows with newly announced episodes…");
  try {
    const data = await api("/api/releases/active-shows?days=60");
    const items = data.items;
    state.activeShowsLoaded = true;
    container.innerHTML = items.length ? items.map(cardHtml).join("") : `<div class="empty-state"><span class="empty-monogram" aria-hidden="true">PMT</span><h3>${state.interfaceLanguage === "fr" ? "Aucune série en diffusion confirmée" : "No confirmed active shows"}</h3><p>${state.interfaceLanguage === "fr" ? "Lancez une vérification de la bibliothèque. Une série apparaît seulement lorsqu’un fournisseur pris en charge annonce un épisode dans les 60 prochains jours." : "Run a library check. A show appears only when a supported provider has announced an episode within the next 60 days."}</p></div>`;
    showMessage($("#active-shows-state"), items.length ? countText(items.length, "active show", "active shows", "série en diffusion", "séries en diffusion") : "");
    bindCards(container);
    await loadReleaseOverview();
  } catch (error) {
    container.innerHTML = "";
    showMessage($("#active-shows-state"), error.message, true);
  } finally { container.setAttribute("aria-busy", "false"); }
}

function releaseEpisodeLabel(item) {
  const season = `S${String(item.season_number ?? 0).padStart(2, "0")}`;
  const episode = `E${String(item.episode_number ?? 0).padStart(2, "0")}`;
  return `${season}${episode}`;
}

async function loadReleaseOverview() {
  try {
    const [data, sync] = await Promise.all([
      api("/api/releases/currently-watching"),
      api("/api/releases/sync")
    ]);
    const upcoming = data.upcoming || [];
    const next = upcoming[0];
    $("#active-calendar-summary").textContent = next
      ? `${countText(upcoming.length, "dated episode", "dated episodes", "épisode daté", "épisodes datés")} · next ${formatDate(next.air_date)}`
      : interfaceCopy("No dated episodes in the next 60 days", "Aucun épisode daté dans les 60 prochains jours");
    state.releaseCheckMode = sync.mode || null;
    $("#release-check-mode").checked = state.releaseCheckMode === "automatic";
    const progress = $("#release-sync-progress");
    progress.hidden = sync.state !== "running";
    const lastSuccess = sync.last_success_at ? new Date(sync.last_success_at).toLocaleString(interfaceLocale()) : interfaceCopy("Not yet checked", "Pas encore vérifié");
    const nextRun = sync.next_run_at ? new Date(sync.next_run_at).toLocaleString(interfaceLocale()) : null;
    if (sync.state === "running") {
      $("#release-sync-status").textContent = interfaceCopy("Checking verified library shows now… Existing schedules remain available while this finishes.", "Vérification des séries confirmées de la bibliothèque… Les calendriers existants restent disponibles pendant l’opération.");
    } else if (sync.last_error_message) {
      $("#release-sync-status").textContent = state.interfaceLanguage === "fr" ? `${sync.last_error_message} Les données en cache ont été conservées. Dernière réussite : ${lastSuccess}.` : `${sync.last_error_message} Cached schedule data was kept. Last successful: ${lastSuccess}.`;
    } else if (state.releaseCheckMode === "automatic") {
      $("#release-sync-status").textContent = state.interfaceLanguage === "fr" ? `Automatique pendant l’ouverture de PMT · Dernière réussite : ${lastSuccess}.${nextRun ? ` Prochaine vérification : ${nextRun}.` : ""}` : `Automatic while PMT is open · Last successful: ${lastSuccess}.${nextRun ? ` Next check: ${nextRun}.` : ""}`;
    } else {
      $("#release-sync-status").textContent = state.interfaceLanguage === "fr" ? `Vérifications manuelles · Dernière réussite : ${lastSuccess}. Une nouvelle vérification réutilise les calendriers encore à jour.` : `Manual checks only · Last successful: ${lastSuccess}. A new library check reuses schedules that are still current.`;
    }
    clearTimeout(state.releasePollTimer);
    if (sync.state === "running" && state.view === "active_shows") {
      state.releasePollTimer = setTimeout(loadReleaseOverview, 1200);
    }
  } catch (error) {
    $("#active-calendar-summary").textContent = `${interfaceCopy("Schedule unavailable", "Calendrier indisponible")} · ${error.message}`;
  }
}

async function syncAllReleases() {
  const button = $("#sync-releases");
  button.disabled = true;
  button.textContent = interfaceCopy("Checking…", "Vérification…");
  $("#release-sync-progress").hidden = false;
  $("#release-sync-status").textContent = interfaceCopy("Checking verified TV and anime entries in your library… This can take longer for a large library.", "Vérification des séries et anime confirmés dans votre bibliothèque… Cela peut prendre plus de temps pour une grande bibliothèque.");
  try {
    const result = await api("/api/releases/sync", {method: "POST", body: "{}"});
    if (result.status === "already_running") {
      toast(interfaceCopy("A release check is already running", "Une vérification des sorties est déjà en cours"));
    } else if (!result.total) {
      toast(state.interfaceLanguage === "fr"
        ? `Bibliothèque déjà à jour · ${result.fresh || 0} calendriers en cache · anime pris en charge : ${result.eligible_anime || 0}/${result.anime_total || 0}`
        : `Library already current · ${result.fresh || 0} cached schedules · anime supported: ${result.eligible_anime || 0}/${result.anime_total || 0}`);
    } else {
      toast(state.interfaceLanguage === "fr"
        ? `Vérification terminée · ${result.synced} calendriers actualisés sur ${result.scope_total || result.total} titres épisodiques · anime pris en charge : ${result.eligible_anime || 0}/${result.anime_total || 0}${result.failed ? ` · ${result.failed} ont conservé les données en cache` : ""}`
        : `Library check complete · ${result.synced} schedules refreshed across ${result.scope_total || result.total} episodic titles · anime supported: ${result.eligible_anime || 0}/${result.anime_total || 0}${result.failed ? ` · ${result.failed} kept cached data` : ""}`);
    }
    state.libraryLoaded = false;
    state.currentlyWatchingLoaded = false;
    state.activeShowsLoaded = false;
    await loadActiveShows();
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.innerHTML = `<svg class="button-icon" aria-hidden="true"><use href="#icon-refresh"></use></svg> ${interfaceCopy("Check library now", "Vérifier la bibliothèque")}`; }
}

async function saveReleaseCheckMode(mode) {
  if (!["manual", "automatic"].includes(mode)) return;
  const toggle = $("#release-check-mode");
  toggle.disabled = true;
  try {
    await api("/api/settings/general", {method: "PUT", body: JSON.stringify({release_check_mode: mode})});
    state.releaseCheckMode = mode;
    toggle.checked = mode === "automatic";
    toast(mode === "automatic"
      ? interfaceCopy("Automatic release checks enabled while PMT is open", "Vérifications automatiques activées pendant que PMT est ouvert")
      : interfaceCopy("Release checks set to manual", "Vérifications des sorties réglées en mode manuel"));
    await loadReleaseOverview();
  } catch (error) {
    toggle.checked = state.releaseCheckMode === "automatic";
    toast(error.message);
  } finally { await loadPersonalTailscale(); }
}

function seriesEpisodeHtml(episode) {
  const future = episode.air_date && episode.air_date > new Date().toISOString().slice(0, 10);
  const unavailable = !episode.air_date || future;
  return `<article class="episode-row ${episode.watched ? "is-watched" : ""} ${unavailable ? "is-future" : ""}" data-episode="${episode.id}"><span class="episode-number">${episode.episode_number ?? "—"}</span><div class="episode-copy"><strong translate="no">${esc(episode.title || translatedText("Untitled episode"))}</strong><p>${episode.air_date ? `Air date ${esc(formatDate(episode.air_date))}` : "Air date TBA"}${episode.runtime_minutes ? ` · ${episode.runtime_minutes} min` : ""}</p>${episode.overview ? `<details class="spoiler-overview"><summary>Show provider summary</summary><p translate="no">${esc(episode.overview)}</p></details>` : ""}</div><button type="button" class="quiet" data-toggle-episode ${unavailable && !episode.watched ? `disabled title="Available after a confirmed air date"` : ""}>${episode.watched ? "Mark unwatched" : unavailable ? "Not released" : "Mark watched"}</button></article>`;
}

function showSeasonDrawer(season, panel) {
  state.openSeasonId = season.id;
  const drawer = $(".season-drawer", panel);
  drawer.hidden = false;
  drawer.dataset.season = season.id;
  drawer.innerHTML = `<div class="season-drawer-head"><div><p class="eyebrow">Episodes</p><h3>${season.season_number === 0 ? "Specials" : `Season ${season.season_number}`}${season.title && !/^season \d+$/i.test(season.title) ? ` · <span translate="no">${esc(season.title)}</span>` : ""}</h3><p class="muted">${season.air_date ? `First air date ${esc(formatDate(season.air_date))}` : "Air date unknown"}</p></div><button type="button" class="icon-button quiet" data-close-season aria-label="Close episodes" title="Close episodes"><svg aria-hidden="true"><use href="#icon-close"></use></svg></button></div><div class="season-actions"><button type="button" class="quiet" data-season-watched="true">Mark season watched</button><button type="button" class="quiet" data-season-watched="false">Mark season unwatched</button></div><div class="season-episodes">${season.episodes.length ? season.episodes.map(seriesEpisodeHtml).join("") : `<p class="muted">No episode records were returned for this season.</p>`}</div>`;
  $$(".season-card", panel).forEach(card => {
    const active = card.dataset.season === season.id;
    card.classList.toggle("active", active);
    const button = $(".season-card-button", card);
    button.setAttribute("aria-expanded", String(active));
    button.setAttribute("aria-label", `${active ? "Collapse" : "Open"} ${card.dataset.seasonNumber === "0" ? "specials" : `season ${card.dataset.seasonNumber}`} episodes`);
  });
  $("[data-close-season]", drawer).addEventListener("click", () => closeSeasonDrawer(panel));
  $$('[data-toggle-episode]', drawer).forEach(button => button.addEventListener("click", () => toggleEpisode(button.closest("[data-episode]"))));
  $$('[data-season-watched]', drawer).forEach(button => button.addEventListener("click", () => bulkSeason(season.id, button.dataset.seasonWatched === "true")));
}

function closeSeasonDrawer(panel) {
  state.openSeasonId = null;
  const drawer = $(".season-drawer", panel);
  drawer.hidden = true;
  drawer.removeAttribute("data-season");
  $$(".season-card", panel).forEach(card => {
    card.classList.remove("active");
    const button = $(".season-card-button", card);
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-label", `Open ${card.dataset.seasonNumber === "0" ? "specials" : `season ${card.dataset.seasonNumber}`} episodes`);
  });
}

function toggleSeasonDrawer(season, panel) {
  if (state.openSeasonId === season.id && !$(".season-drawer", panel).hidden) {
    closeSeasonDrawer(panel);
    return;
  }
  showSeasonDrawer(season, panel);
}

function renderSeriesReleases(data) {
  const panel = $("#series-release-panel");
  if (!data.supported) {
    panel.innerHTML = `<div class="empty-state"><h3>Automatic tracking needs a verified series identity</h3><p>This entry remains fully usable. Attach an exact TVmaze, TMDb TV, or Kitsu match from the Metadata tab before following releases; dates are never guessed from a title.</p><div class="empty-actions"><button type="button" class="quiet" data-entry-open-metadata>Open Metadata</button></div></div>`;
    $("[data-entry-open-metadata]", panel).addEventListener("click", () => selectEntryTab("metadata"));
    return;
  }
  if (!data.subscription?.enabled) {
    panel.innerHTML = `<div class="empty-state"><h3>Follow ${esc(data.title)} for episode progress</h3><p>Following stores normalized provider air dates and lets you mark episodes yourself. It never marks episodes watched or changes the show’s status.</p><div class="empty-actions"><button type="button" id="follow-series">Follow series</button></div></div>`;
    $("#follow-series").addEventListener("click", followCurrentSeries);
    return;
  }
  const subscription = data.subscription;
  const progress = data.progress.released ? Math.min(data.progress.watched / data.progress.released * 100, 100) : 0;
  const seasons = data.seasons.filter(season => subscription.include_specials || season.season_number !== 0);
  panel.innerHTML = `<div class="series-release-layout"><div class="series-release-main"><div class="series-source-panel"><div><strong>${esc(subscription.provider_source || "Provider")} schedule source</strong><p class="muted">Last attempted: ${subscription.last_attempt_at ? esc(new Date(subscription.last_attempt_at).toLocaleString(interfaceLocale())) : "Never"}<br>Last successful: ${subscription.last_success_at ? esc(new Date(subscription.last_success_at).toLocaleString(interfaceLocale())) : "Never"}</p>${subscription.last_error_message ? `<p class="message error">${esc(subscription.last_error_message)} Cached episodes were kept.</p>` : ""}</div><span class="chip">Air dates only</span></div><div class="series-actions"><button type="button" id="sync-current-series">Sync now</button><button type="button" id="toggle-specials" class="quiet">${subscription.include_specials ? "Hide specials" : "Include specials"}</button><button type="button" id="unfollow-series" class="quiet-danger">Stop following</button></div><div class="episode-progress" role="progressbar" aria-valuemin="0" aria-valuemax="${data.progress.released}" aria-valuenow="${data.progress.watched}"><span style="width:${progress}%"></span></div><p class="muted series-progress-copy">${data.progress.watched} watched · ${data.progress.released} released · ${data.progress.total} total known. Future air dates never mark an episode watched.</p><div class="season-list">${seasons.length ? seasons.map(season => `<article class="season-card ${state.openSeasonId === season.id ? "active" : ""}" data-season="${season.id}" data-season-number="${season.season_number}"><button type="button" class="season-card-button" aria-expanded="${state.openSeasonId === season.id}" aria-controls="season-episode-drawer" aria-label="${state.openSeasonId === season.id ? "Collapse" : "Open"} ${season.season_number === 0 ? "specials" : `season ${season.season_number}`} episodes"><span>${season.season_number === 0 ? "Specials" : `Season ${season.season_number}`}${season.title && !/^season \d+$/i.test(season.title) ? ` · <span translate="no">${esc(season.title)}</span>` : ""}</span><span class="season-card-tail"><span class="chip">${season.watched_count}/${season.episodes.length} watched</span><svg aria-hidden="true"><use href="#icon-chevron"></use></svg></span></button></article>`).join("") : `<div class="empty-state"><h3>No season schedule is cached yet</h3><p>Choose Sync now. A provider failure will leave any existing cache untouched.</p></div>`}</div></div><aside id="season-episode-drawer" class="season-drawer" hidden aria-live="polite"></aside></div>`;
  $("#sync-current-series").addEventListener("click", syncCurrentSeries);
  $("#toggle-specials").addEventListener("click", () => updateCurrentSubscription({include_specials: !subscription.include_specials}));
  $("#unfollow-series").addEventListener("click", unfollowCurrentSeries);
  $$(".season-card-button", panel).forEach((button, index) => button.addEventListener("click", () => toggleSeasonDrawer(seasons[index], panel)));
  const selectedSeason = seasons.find(season => season.id === state.openSeasonId);
  if (selectedSeason) showSeasonDrawer(selectedSeason, panel);
}

async function loadEntryReleases() {
  if (!state.currentEntry) return;
  if (state.releaseEntryId !== state.currentEntry.id) {
    state.releaseEntryId = state.currentEntry.id;
    state.openSeasonId = null;
  }
  $("#series-release-panel").innerHTML = `<p class="muted">Loading normalized episode records…</p>`;
  try { renderSeriesReleases(await api(`/api/series/${state.currentEntry.id}`)); }
  catch (error) { $("#series-release-panel").innerHTML = `<p class="message error">${esc(error.message)}</p>`; }
}

async function followCurrentSeries() {
  try {
    await api(`/api/series/${state.currentEntry.id}/subscription`, {method: "PUT", body: JSON.stringify({notify_new_episode: true, notify_new_season: true, include_specials: false})});
    await syncCurrentSeries();
    toast("Series followed");
  } catch (error) { toast(error.message); }
}

async function updateCurrentSubscription(overrides) {
  try {
    const detail = await api(`/api/series/${state.currentEntry.id}`);
    const subscription = detail.subscription || {};
    await api(`/api/series/${state.currentEntry.id}/subscription`, {method: "PUT", body: JSON.stringify({notify_new_episode: subscription.notify_new_episode ?? true, notify_new_season: subscription.notify_new_season ?? true, include_specials: subscription.include_specials ?? false, ...overrides})});
    await loadEntryReleases();
    state.currentlyWatchingLoaded = false;
    state.activeShowsLoaded = false;
    state.calendarLoaded = false;
  } catch (error) { toast(error.message); }
}

async function syncCurrentSeries() {
  try {
    $("#sync-current-series")?.setAttribute("disabled", "");
    const data = await api(`/api/series/${state.currentEntry.id}/sync`, {method: "POST", body: "{}"});
    renderSeriesReleases(data);
    state.currentlyWatchingLoaded = false;
    state.activeShowsLoaded = false;
    state.calendarLoaded = false;
    toast("Release schedule updated");
  } catch (error) { toast(`${error.message} Cached schedule data was kept.`); }
}

async function unfollowCurrentSeries() {
  if (!await confirmAction("Stop following this series?", "Cached seasons, episode progress, and existing notifications will be retained. Automatic checks will stop.", "Stop following")) return;
  try {
    await api(`/api/series/${state.currentEntry.id}/subscription`, {method: "DELETE"});
    state.currentlyWatchingLoaded = false;
    state.activeShowsLoaded = false;
    state.calendarLoaded = false;
    await loadEntryReleases();
  } catch (error) { toast(error.message); }
}

async function toggleEpisode(row) {
  const watched = row.classList.contains("is-watched");
  try {
    const data = await api(`/api/episodes/${row.dataset.episode}/viewing`, {method: watched ? "DELETE" : "PUT", body: watched ? undefined : "{}"});
    const episode = data.seasons.flatMap(season => season.episodes).find(item => item.id === row.dataset.episode);
    if (!episode) throw new Error("The updated episode could not be found.");
    row.classList.toggle("is-watched", episode.watched);
    const button = $("[data-toggle-episode]", row);
    button.textContent = episode.watched ? "Mark unwatched" : "Mark watched";
    row.classList.remove("episode-just-updated");
    void row.offsetWidth;
    row.classList.add("episode-just-updated");
    row.addEventListener("animationend", () => row.classList.remove("episode-just-updated"), {once: true});
    const progress = $(".episode-progress", $("#series-release-panel"));
    const percent = data.progress.released ? Math.min(data.progress.watched / data.progress.released * 100, 100) : 0;
    progress.setAttribute("aria-valuemax", String(data.progress.released));
    progress.setAttribute("aria-valuenow", String(data.progress.watched));
    $("span", progress).style.width = `${percent}%`;
    $(".series-progress-copy", $("#series-release-panel")).textContent = `${data.progress.watched} watched · ${data.progress.released} released · ${data.progress.total} total known. Future air dates never mark an episode watched.`;
    const season = data.seasons.find(item => item.episodes.some(candidate => candidate.id === episode.id));
    const seasonChip = season ? $(".season-card-tail .chip", $(`.season-card[data-season='${season.id}']`, $("#series-release-panel"))) : null;
    if (seasonChip) seasonChip.textContent = `${season.watched_count}/${season.episodes.length} watched`;
    state.currentlyWatchingLoaded = false;
    state.activeShowsLoaded = false;
    state.calendarLoaded = false;
  } catch (error) { toast(error.message); }
}

async function bulkSeason(seasonId, watched) {
  if (!await confirmAction(`${watched ? "Mark" : "Clear"} the whole season?`, `This will ${watched ? "mark every known episode watched" : "remove every episode watch mark"}. It will not change the show status or title-level viewing count.`, watched ? "Mark season watched" : "Clear season")) return;
  try {
    const data = await api(`/api/seasons/${seasonId}/viewing`, {method: "PUT", body: JSON.stringify({watched, confirmed: true})});
    renderSeriesReleases(data);
    state.currentlyWatchingLoaded = false;
    state.activeShowsLoaded = false;
    state.calendarLoaded = false;
  } catch (error) { toast(error.message); }
}

async function openReleaseCalendar() {
  switchView("calendar", {push: true, scrollTop: true});
  await loadReleaseCalendar();
}

async function loadReleaseCalendar() {
  $("#release-calendar").setAttribute("aria-busy", "true");
  $("#release-calendar").innerHTML = librarySkeletons();
  try {
    const data = await api("/api/releases/upcoming?days=366");
    state.upcomingReleases = data.items;
    state.calendarLoaded = true;
    renderReleaseCalendar();
  } catch (error) { $("#release-calendar").innerHTML = `<p class="message error">${esc(error.message)}</p>`; }
  finally { $("#release-calendar").setAttribute("aria-busy", "false"); }
}

function renderReleaseCalendar() {
  const root = $("#release-calendar");
  if (!state.upcomingReleases.length) {
    root.innerHTML = `<div class="empty-state"><h3>${interfaceCopy("No upcoming dated episodes", "Aucun épisode daté à venir")}</h3><p>${interfaceCopy("Run a library check to cache verified schedules. Unknown provider dates are never placed on the calendar.", "Vérifiez la bibliothèque pour enregistrer les calendriers confirmés. Les dates inconnues du fournisseur ne sont jamais ajoutées au calendrier.")}</p></div>`;
    return;
  }
  const focusDate = new Date(`${state.upcomingReleases[0].air_date}T12:00:00`);
  const first = new Date(focusDate.getFullYear(), focusDate.getMonth(), 1);
  const gridStart = new Date(first);
  gridStart.setDate(first.getDate() - first.getDay());
  const weekdays = Array.from({length: 7}, (_, index) => new Intl.DateTimeFormat(interfaceLocale(), {weekday: "short"}).format(new Date(2024, 0, 7 + index)));
  const events = new Map();
  state.upcomingReleases.forEach(item => {
    if (!events.has(item.air_date)) events.set(item.air_date, []);
    events.get(item.air_date).push(item);
  });
  const days = Array.from({length: 42}, (_, index) => {
    const value = new Date(gridStart);
    value.setDate(gridStart.getDate() + index);
    const key = `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
    const outside = value.getMonth() !== focusDate.getMonth();
    return `<div class="calendar-day ${outside ? "is-outside" : ""}"><span>${value.getDate()}</span>${(events.get(key) || []).map(item => { const index = state.upcomingReleases.indexOf(item); const episode = item.episode_title || interfaceCopy("Untitled episode", "Épisode sans titre"); return `<button type="button" class="calendar-event" data-calendar-index="${index}" data-tip="${esc(`${item.title} · ${releaseEpisodeLabel(item)} ${episode} · ${formatDate(item.air_date)}`)}" aria-label="${esc(`${item.title}, ${releaseEpisodeLabel(item)}, ${episode}, ${formatDate(item.air_date)}`)}"><span translate="no">${esc(item.title)}</span> ${esc(releaseEpisodeLabel(item))}</button>`; }).join("")}</div>`;
  });
  root.innerHTML = `<h3>${focusDate.toLocaleDateString(interfaceLocale(), {month: "long", year: "numeric"})}</h3><div class="calendar-month">${weekdays.map(day => `<div class="calendar-weekday">${esc(day)}</div>`).join("")}${days.join("")}</div>`;
  $$('[data-calendar-index]', root).forEach(button => {
    const item = state.upcomingReleases[Number(button.dataset.calendarIndex)];
    button.addEventListener("mouseenter", () => showHelpTooltip(button));
    button.addEventListener("pointerenter", () => showHelpTooltip(button));
    button.addEventListener("mouseleave", hideHelpTooltip);
    button.addEventListener("pointerleave", hideHelpTooltip);
    button.addEventListener("focus", () => {
      if (button.matches(":focus-visible")) showHelpTooltip(button);
    });
    button.addEventListener("blur", hideHelpTooltip);
    button.addEventListener("click", () => renderCalendarSelection(item));
  });
}

function renderCalendarSelection(item) {
  if (!item) return;
  const panel = $("#calendar-selection");
  panel.innerHTML = `<p class="eyebrow">Confirmed provider air date</p><h3 translate="no">${esc(item.title)}</h3><p><strong>${esc(releaseEpisodeLabel(item))}</strong> · <span translate="no">${esc(item.episode_title || interfaceCopy("Untitled episode", "Épisode sans titre"))}</span></p><dl class="calendar-selection-facts"><div><dt>Air date</dt><dd>${esc(formatDate(item.air_date))}</dd></div><div><dt>Source</dt><dd>${esc(item.provider_source || "TMDB")}</dd></div></dl><p class="muted">An air date does not guarantee streaming availability.</p><button type="button" id="open-calendar-selection">Open episodes &amp; releases</button>`;
  $("#open-calendar-selection").addEventListener("click", () => openEntry(item.entry_id, "releases"));
}

async function openReleaseNotifications() {
  switchView("notifications", {push: true, scrollTop: true});
}

function rankingHtml(row) {
  const entry = row.entry;
  const item = entry.catalog_item;
  const title = item.canonical_title;
  const technical = row.technical_score != null;
  const delta = technical ? Number(row.technical_score) - Number(row.personal_rating) : 0;
  const direction = delta > 0.045 ? "higher" : delta < -0.045 ? "lower" : "same";
  const evidenceLabels = {base: "Not refined", developing: "Developing evidence", supported: "Supported", well_supported: "Well supported"};
  const evidence = row.refined ? (evidenceLabels[row.evidence_level] || row.evidence_level) : "Not refined";
  const mediaArtwork = safeImageUrl(entryPoster(item));
  return `<article class="ranking-tile" data-entry="${entry.id}" data-media-hue="${titleHue(title)}"${mediaArtwork ? ` data-media-art="${esc(mediaArtwork)}"` : ""} style="--media-hue:${titleHue(title)}" aria-label="${esc(translatedText(`Rank ${row.rank}, ${title}`))}">
    <span class="ranking-position" aria-hidden="true">${row.rank}</span>
    ${imageHtml(entryPoster(item), title, "poster", interfaceCopy(`Poster for ${title}`, `Affiche de ${title}`))}
    <div class="ranking-copy"><h3 translate="no">${esc(title)}</h3><p class="entry-meta">${esc(item.release_year || translatedText("Year unknown"))} · ${esc(mediaLabel(item.media_type))}</p></div>
    <div class="ranking-scores ${technical ? direction : "personal"}">${technical ? `<span><small>${esc(translatedText("Your rating"))}</small><strong>${formatRating(row.personal_rating)}</strong></span><span class="technical-score"><small>${esc(translatedText("Technical"))}</small><strong>${formatRating(row.technical_score)}</strong><em>${direction === "same" ? esc(translatedText("No change")) : `${delta > 0 ? "▲" : "▼"} ${formatRating(Math.abs(delta))}`}</em></span>` : `<span><small>${esc(translatedText("Your rating"))}</small><strong>${formatRating(row.personal_rating)}</strong></span>`}</div>
    <div class="ranking-footer">${technical ? `<div class="ranking-evidence"><span class="chip evidence-chip ${row.refined ? "" : "unrefined"}">${esc(translatedText(evidence))}</span>${row.comparison_count ? `<span class="muted">${esc(countText(row.comparison_count, "comparison", "comparisons", "comparaison", "comparaisons"))}</span>` : ""}</div>` : `<span></span>`}<button type="button" class="quiet media-info-button" data-ranking-details aria-label="${esc(interfaceCopy(`Information about ${title}`, `Informations sur ${title}`))}" title="${esc(interfaceCopy("More information", "Plus d’informations"))}"><svg aria-hidden="true"><use href="#icon-info"></use></svg></button></div>
  </article>`;
}

async function loadRankings() {
  const container = $("#rankings-list");
  container.setAttribute("aria-busy", "true");
  container.innerHTML = librarySkeletons();
  showMessage($("#rankings-state"), interfaceCopy("Loading rankings…", "Chargement des classements…"));
  try {
    const settings = await api("/api/settings/general");
    state.advancedRatingsEnabled = Boolean(settings.advanced_ratings_enabled);
    if (!state.advancedRatingsEnabled) state.rankingMode = "personal";
    const modeControl = $("#rankings-mode-control");
    modeControl.hidden = !state.advancedRatingsEnabled;
    $("#refine-rankings").hidden = !state.advancedRatingsEnabled;
    $("#technical-score-help").hidden = !state.advancedRatingsEnabled || state.rankingMode !== "technical";
    $("#rankings-technical-mode").checked = state.rankingMode === "technical";
    const params = new URLSearchParams({mode: state.rankingMode, show_all: "true"});
    const form = new FormData($("#rankings-filter-form"));
    for (const [key, value] of form.entries()) if (String(value).trim()) params.set(key, String(value).trim());
    const data = await api(`/api/rankings?${params}`);
    state.rankingsLoaded = true;
    container.innerHTML = data.items.length ? data.items.map(rankingHtml).join("") : `<div class="empty-state"><span class="empty-monogram" aria-hidden="true">PMT</span><h3>${interfaceCopy("No rated titles yet", "Aucun titre noté")}</h3><p>${interfaceCopy("Add a personal rating to any Library title to begin your ranking.", "Ajoutez une note personnelle à un titre de la bibliothèque pour commencer votre classement.")}</p></div>`;
    $("#rankings-help").textContent = state.rankingMode === "technical"
      ? interfaceCopy("Technical order stays anchored to your 1–10 ratings, then applies small bounded adjustments from completed assessments and comparisons.", "L’ordre technique reste ancré à vos notes de 1 à 10, puis applique de petits ajustements limités issus des questionnaires et comparaisons terminés.")
      : interfaceCopy("Ranked directly by your personal 1–10 rating. Ties use a stable title order.", "Classement direct selon votre note personnelle de 1 à 10. Les égalités utilisent un ordre stable par titre.");
    showMessage($("#rankings-state"), countText(data.total, "rated title", "rated titles", "titre noté", "titres notés"));
    $$("[data-ranking-details]", container).forEach(button => button.addEventListener("click", () => openEntry(button.closest("[data-entry]").dataset.entry)));
    bindPosterFallbacks(container);
  } catch (error) {
    container.innerHTML = "";
    showMessage($("#rankings-state"), error.message, true);
  } finally { container.setAttribute("aria-busy", "false"); }
}

async function ensureRatingRubric() {
  if (!state.ratingRubric) state.ratingRubric = await api("/api/ratings/rubric");
  return state.ratingRubric;
}

function assessmentQuestionHtml(dimension, answer) {
  const localized = rubricCatalogs[state.interfaceLanguage]?.[dimension.key];
  const prompt = localized ? localized[0] : dimension.prompt;
  const lowLabel = localized ? localized[1] : dimension.low_label;
  const highLabel = localized ? localized[2] : dimension.high_label;
  const values = state.ratingRubric?.answer_values || [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5];
  const choices = values.map(value => `<label><input type="radio" name="assessment-${esc(dimension.key)}" value="${value}" ${Number(answer) === value ? "checked" : ""}><span>${value}</span></label>`).join("");
  const notApplicable = dimension.group === "optional" ? `<label class="assessment-skip"><input type="radio" name="assessment-${esc(dimension.key)}" value="not_applicable" ${answer === "not_applicable" ? "checked" : ""}><span>N/A</span></label>` : "";
  return `<fieldset class="assessment-question" data-dimension="${esc(dimension.key)}"><legend>${esc(prompt)}</legend><div class="assessment-scale">${choices}<label class="assessment-skip"><input type="radio" name="assessment-${esc(dimension.key)}" value="skip" ${answer === "skip" ? "checked" : ""}><span>${esc(interfaceCopy("Don’t remember", "Je ne me souviens pas"))}</span></label>${notApplicable}</div><div class="assessment-endpoints"><span>${esc(lowLabel)}</span><span>${esc(highLabel)}</span></div></fieldset>`;
}

function renderAssessment() {
  const assessment = state.currentAssessment;
  const rubric = state.ratingRubric;
  if (!assessment || !rubric) return;
  const dimensions = rubric.dimensions;
  const reviewing = state.assessmentStep >= dimensions.length;
  $("#assessment-core").hidden = reviewing;
  $("#assessment-review").hidden = !reviewing;
  $("#next-assessment-question").hidden = reviewing;
  $("#complete-assessment").hidden = !reviewing;
  $("#previous-assessment-question").disabled = state.assessmentStep === 0;
  if (reviewing) {
    $("#assessment-question-progress").textContent = interfaceCopy("Review your evidence", "Vérifiez vos réponses");
    $("#assessment-core").innerHTML = "";
    renderAssessmentPreview(assessment);
    return;
  }
  const dimension = dimensions[state.assessmentStep];
  $("#assessment-question-progress").textContent = interfaceCopy(`Question ${state.assessmentStep + 1} of ${dimensions.length}${dimension.group === "optional" ? " · optional" : ""}`, `Question ${state.assessmentStep + 1} sur ${dimensions.length}${dimension.group === "optional" ? " · facultative" : ""}`);
  $("#assessment-core").innerHTML = assessmentQuestionHtml(dimension, assessment.answers[dimension.key]);
  const next = $("#next-assessment-question");
  next.textContent = state.assessmentStep === dimensions.length - 1 ? interfaceCopy("Continue to review", "Continuer vers la vérification") : translatedText("Continue");
  next.disabled = !(dimension.key in assessment.answers);
  $$("input[type='radio']", $("#assessment-core")).forEach(input => input.addEventListener("change", () => {
    assessment.answers[dimension.key] = /^\d+(\.5)?$/.test(input.value) ? Number(input.value) : input.value;
    next.disabled = false;
    showMessage($("#assessment-message"), "");
  }));
}

function renderAssessmentPreview(assessment) {
  const preview = $("#assessment-preview");
  const minimum = assessment.minimum_core_answers || state.ratingRubric?.minimum_core_answers || 4;
  const total = assessment.core_total || state.ratingRubric?.dimensions?.filter(item => item.group === "core").length || 6;
  const coreKeys = new Set(state.ratingRubric?.dimensions?.filter(item => item.group === "core").map(item => item.key) || []);
  const coreAnswered = Object.entries(assessment.answers || {}).filter(([key, value]) => coreKeys.has(key) && typeof value === "number").length;
  if (coreAnswered < minimum) {
    preview.innerHTML = `<strong>${interfaceCopy(`Answer at least ${minimum} core questions to save usable evidence.`, `Répondez à au moins ${minimum} questions principales pour enregistrer des données utilisables.`)}</strong><p>${interfaceCopy(`${coreAnswered} of ${total} core questions answered. “Don’t remember” and N/A answers add no evidence.`, `${coreAnswered} questions principales répondues sur ${total}. « Je ne me souviens pas » et N/A n’ajoutent aucune donnée.`)}</p>`;
    $("#complete-assessment").disabled = true;
    return;
  }
  preview.innerHTML = `<strong>${interfaceCopy("Usable evidence ready", "Données utilisables prêtes")}</strong><p>${interfaceCopy(`${coreAnswered} of ${total} core questions answered. Skipped answers are excluded so uncertain memories cannot lower refinement quality.`, `${coreAnswered} questions principales répondues sur ${total}. Les réponses ignorées sont exclues afin que les souvenirs incertains ne réduisent pas la qualité.`)}</p>`;
  $("#complete-assessment").disabled = false;
}

function collectAssessmentAnswers() {
  return {...(state.currentAssessment?.answers || {})};
}

function refinementProgressHtml(run, label) {
  const percent = Math.max(0, Math.min(100, Number(run?.overall_percent || 0)));
  const steps = interfaceCopy(`${run.overall_completed} of ${run.overall_target} steps`, `${run.overall_completed} étapes sur ${run.overall_target}`);
  return `<div class="refinement-progress-copy"><strong>${esc(label)}</strong><span>${steps} · ${percent}%</span></div><div class="refinement-progress-track" role="progressbar" aria-label="${esc(translatedText("Overall refinement progress"))}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><span style="width:${percent}%"></span></div>`;
}

async function openAssessment(entryId, {run = state.refinementRun} = {}) {
  if (!state.advancedRatingsEnabled) {
    toast(interfaceCopy("Enable Advanced ratings in Settings first", "Activez d’abord les notes avancées dans les réglages"));
    return;
  }
  if (!run || run.stage !== "assessments") {
    toast(interfaceCopy("Start or resume Refine rankings first", "Commencez ou reprenez d’abord l’affinement du classement"));
    return;
  }
  try {
    const [rubric, entry, assessment] = await Promise.all([
      ensureRatingRubric(),
      api(`/api/entries/${entryId}`),
      api("/api/ratings/assessments", {method: "POST", body: JSON.stringify({entry_id: entryId})})
    ]);
    state.ratingRubric = rubric;
    state.assessmentEntry = entry;
    state.currentAssessment = assessment;
    state.refinementRun = run;
    const firstUnanswered = rubric.dimensions.findIndex(item => !(item.key in assessment.answers));
    state.assessmentStep = firstUnanswered === -1 ? rubric.dimensions.length : firstUnanswered;
    $("#assessment-reflection").value = assessment.private_reflection || "";
    $("#assessment-heading").textContent = `${interfaceCopy("Refine", "Affiner")} · ${entry.catalog_item.canonical_title}`;
    const rewatches = Math.max(Number(entry.view_count || 0) - 1, 0);
    $("#assessment-context").textContent = interfaceCopy(`Your rating is ${formatRating(entry.personal_rating)}. Stored viewing context: ${entry.view_count || 0} total view${entry.view_count === 1 ? "" : "s"}, including ${rewatches} rewatch${rewatches === 1 ? "" : "es"}. Rewatches never add points automatically.`, `Votre note est ${formatRating(entry.personal_rating)}. Contexte enregistré : ${entry.view_count || 0} visionnage${entry.view_count === 1 ? "" : "s"} au total, dont ${rewatches} revisionnage${rewatches === 1 ? "" : "s"}. Les revisionnages n’ajoutent jamais automatiquement de points.`);
    const item = entry.catalog_item;
    $("#assessment-memory-card").innerHTML = `${imageHtml(entryPoster(item), item.canonical_title, "poster", interfaceCopy(`Poster for ${item.canonical_title}`, `Affiche de ${item.canonical_title}`))}<div><strong translate="no">${esc(item.canonical_title)}</strong><p class="entry-meta">${esc(item.release_year || translatedText("Year unknown"))} · ${esc(mediaLabel(item.media_type))}</p>${item.overview ? `<p translate="no">${esc(item.overview.slice(0, 280))}</p>` : `<p class="muted">${esc(interfaceCopy("No summary is available; skipping is always safe.", "Aucun résumé n’est disponible ; vous pouvez toujours ignorer ce titre."))}</p>`}</div>`;
    $("#assessment-run-progress").innerHTML = refinementProgressHtml(run, interfaceCopy(`Stage 2 of 2 · Title ${Math.min(run.assessments_completed + 1, run.assessment_target)} of ${run.assessment_target}`, `Étape 2 sur 2 · Titre ${Math.min(run.assessments_completed + 1, run.assessment_target)} sur ${run.assessment_target}`));
    showMessage($("#assessment-message"), assessment.state === "draft" && Object.keys(assessment.answers).length ? interfaceCopy("Resumed your saved draft.", "Votre brouillon enregistré a été repris.") : "");
    renderAssessment();
    bindPosterFallbacks($("#assessment-memory-card"));
    if ($("#entry-dialog").open) $("#entry-dialog").close();
    openDialog($("#assessment-dialog"));
  } catch (error) { toast(error.message); }
}

async function saveAssessmentDraft({silent = false} = {}) {
  const assessment = state.currentAssessment;
  if (!assessment) return null;
  const button = $("#save-assessment-draft");
  button.disabled = true;
  try {
    const updated = await api(`/api/ratings/assessments/${assessment.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        expected_version: assessment.version,
        answers: collectAssessmentAnswers(),
        private_reflection: $("#assessment-reflection").value.trim() || null
      })
    });
    state.currentAssessment = updated;
    renderAssessmentPreview(updated);
    if (!silent) showMessage($("#assessment-message"), interfaceCopy("Draft saved. Your personal rating is unchanged.", "Brouillon enregistré. Votre note personnelle reste inchangée."));
    return updated;
  } catch (error) {
    showMessage($("#assessment-message"), error.message, true);
    return null;
  } finally { button.disabled = false; }
}

async function completeAssessment(ratingAction) {
  const saved = await saveAssessmentDraft({silent: true});
  if (!saved) return;
  const body = {expected_version: saved.version, rating_action: ratingAction, refinement_run_id: state.refinementRun?.id};
  try {
    await api(`/api/ratings/assessments/${saved.id}/complete`, {method: "POST", body: JSON.stringify(body)});
    state.currentAssessment = null;
    state.rankingsLoaded = false;
    state.libraryLoaded = false;
    $("#assessment-dialog").close();
    toast(interfaceCopy("Title evidence saved; your personal rating is unchanged", "Évaluation du titre enregistrée ; votre note personnelle reste inchangée"));
    const run = await api(`/api/ratings/refinement-runs/${state.refinementRun.id}`);
    await continueRefinement(run);
  } catch (error) { showMessage($("#assessment-message"), error.message, true); }
}

function resetAssessmentAnswers() {
  if (state.currentAssessment) state.currentAssessment.answers = {};
  state.assessmentStep = 0;
  $("#assessment-reflection").value = "";
  renderAssessment();
  showMessage($("#assessment-message"), interfaceCopy("Answers cleared locally. Choose Save draft to persist the reset.", "Réponses effacées localement. Enregistrez le brouillon pour conserver cette réinitialisation."));
}

function previousAssessmentQuestion() {
  if (state.assessmentStep > 0) state.assessmentStep -= 1;
  renderAssessment();
}

function nextAssessmentQuestion() {
  const dimensions = state.ratingRubric?.dimensions || [];
  if (state.assessmentStep < dimensions.length) state.assessmentStep += 1;
  renderAssessment();
}

async function skipAssessmentTitle() {
  const run = state.refinementRun;
  const entry = state.assessmentEntry;
  if (!run || !entry) return;
  try {
    const advanced = await api(`/api/ratings/refinement-runs/${run.id}/skip-entry`, {method: "POST", body: JSON.stringify({entry_id: entry.id})});
    state.currentAssessment = null;
    $("#assessment-dialog").close();
    toast(interfaceCopy("Skipped without adding uncertain evidence", "Titre ignoré sans ajouter de données incertaines"));
    await continueRefinement(advanced);
  } catch (error) { showMessage($("#assessment-message"), error.message, true); }
}

function comparisonCardHtml(entry, side) {
  const item = entry.catalog_item;
  return `<article class="comparison-card" data-side="${side}">${imageHtml(entryPoster(item), item.canonical_title, "poster", `Poster for ${item.canonical_title}`)}<div><p class="eyebrow">${interfaceCopy(side === "left" ? "Left" : "Right", side === "left" ? "Gauche" : "Droite")}</p><h3 translate="no">${esc(item.canonical_title)}</h3><p class="muted">${esc(item.release_year || translatedText("Year unknown"))} · ${esc(mediaLabel(item.media_type))}</p><p>${esc(translatedText("Your rating"))} : <strong>${formatRating(entry.personal_rating)}</strong></p></div></article>`;
}

async function loadNextComparison() {
  showMessage($("#comparison-message"), interfaceCopy("Loading a useful nearby pair…", "Chargement d’une paire proche et utile…"));
  try {
    const run = state.refinementRun;
    const data = await api(`/api/ratings/comparisons/next?session_size=10&refinement_run_id=${encodeURIComponent(run.id)}`);
    if (data.refinement) state.refinementRun = data.refinement;
    state.comparisonSession.current = data.pair;
    if (!data.pair) {
      const advanced = await api(`/api/ratings/refinement-runs/${run.id}/finish-comparisons`, {method: "POST", body: "{}"});
      showMessage($("#comparison-message"), interfaceCopy("No additional useful pair is available, so the title-evidence stage is ready.", "Aucune autre paire utile n’est disponible ; l’étape d’évaluation des titres est prête."));
      await continueRefinement(advanced);
      return;
    }
    $("#comparison-cards").innerHTML = comparisonCardHtml(data.pair.left, "left") + comparisonCardHtml(data.pair.right, "right");
    bindPosterFallbacks($("#comparison-cards"));
    $("#comparison-progress").innerHTML = refinementProgressHtml(run, interfaceCopy(`Stage 1 of 2 · Comparison ${Math.min(run.comparisons_completed + 1, run.comparison_target)} of ${run.comparison_target}`, `Étape 1 sur 2 · Comparaison ${Math.min(run.comparisons_completed + 1, run.comparison_target)} sur ${run.comparison_target}`));
    showMessage($("#comparison-message"), data.pair.selection_reason === "rubric_disagreement" ? interfaceCopy("Selected because nearby rubric evidence may clarify the order.", "Sélectionnés parce que leurs évaluations proches peuvent clarifier l’ordre.") : interfaceCopy("Selected because these titles are close in the current order.", "Sélectionnés parce que ces titres sont proches dans l’ordre actuel."));
    $$("#prefer-left, #comparison-tie, #prefer-right, #comparison-skip").forEach(button => { button.disabled = false; });
    $("#comparison-back").disabled = !run.can_undo_comparison;
  } catch (error) { showMessage($("#comparison-message"), error.message, true); }
}

async function answerComparison(choice) {
  const pair = state.comparisonSession.current;
  if (!pair) return;
  const [low] = pair.pair_key.split("~");
  let result = choice;
  if (choice === "left") result = pair.left.id === low ? "low" : "high";
  if (choice === "right") result = pair.right.id === low ? "low" : "high";
  try {
    const response = await api(`/api/ratings/comparisons/${pair.pair_key}`, {method: "PUT", body: JSON.stringify({result, displayed_left_entry_id: pair.left.id, refinement_run_id: state.refinementRun.id})});
    state.refinementRun = response.refinement;
    state.rankingsLoaded = false;
    if (response.refinement.stage !== "comparisons") await continueRefinement(response.refinement);
    else await loadNextComparison();
  } catch (error) { showMessage($("#comparison-message"), error.message, true); }
}

async function undoComparison() {
  const run = state.refinementRun;
  if (!run?.can_undo_comparison) return;
  $("#comparison-back").disabled = true;
  try {
    state.refinementRun = await api(`/api/ratings/refinement-runs/${run.id}/undo-comparison`, {method: "POST", body: "{}"});
    state.rankingsLoaded = false;
    await loadNextComparison();
    showMessage($("#comparison-message"), interfaceCopy("Previous choice removed. Answer that comparison again.", "Le choix précédent a été supprimé. Répondez à nouveau à cette comparaison."));
  } catch (error) { showMessage($("#comparison-message"), error.message, true); }
}

async function continueRefinement(run) {
  state.refinementRun = run;
  if ($("#refinement-scope-dialog").open) $("#refinement-scope-dialog").close();
  if (run.state === "completed" || run.stage === "complete") {
    if ($("#comparison-dialog").open) $("#comparison-dialog").close();
    if ($("#assessment-dialog").open) $("#assessment-dialog").close();
    state.rankingsLoaded = false;
    toast(interfaceCopy("Ranking refinement complete", "Affinement du classement terminé"));
    if (state.view === "rankings") await loadRankings();
    return;
  }
  if (run.stage === "comparisons") {
    if ($("#assessment-dialog").open) $("#assessment-dialog").close();
    state.comparisonSession = {count: run.comparisons_completed, size: run.comparison_target, current: null, lastPairKey: null};
    openDialog($("#comparison-dialog"));
    await loadNextComparison();
    return;
  }
  if ($("#comparison-dialog").open) $("#comparison-dialog").close();
  if (run.next_entry) await openAssessment(run.next_entry.id, {run});
  else {
    const refreshed = await api(`/api/ratings/refinement-runs/${run.id}`);
    if (refreshed.state === "completed") await continueRefinement(refreshed);
  }
}

async function openRefinementScope() {
  if (!state.advancedRatingsEnabled) { toast(interfaceCopy("Enable Advanced ratings in Settings first", "Activez d’abord les notes avancées dans les réglages")); return; }
  try {
    const data = await api("/api/ratings/refinement-runs/active");
    const active = data.run;
    const resume = $("#active-refinement-resume");
    const choices = $(".refinement-scope-grid", $("#refinement-scope-dialog"));
    resume.hidden = !active;
    choices.hidden = Boolean(active);
    if (active) {
      state.refinementRun = active;
      const scopeLabel = active.scope === "full" ? interfaceCopy("Entire library", "Toute la bibliothèque") : interfaceCopy("Focused portion", "Sélection ciblée");
      const stageLabel = active.stage === "comparisons" ? interfaceCopy("comparison stage", "étape des comparaisons") : interfaceCopy("title-evidence stage", "étape d’évaluation des titres");
      resume.innerHTML = `${refinementProgressHtml(active, `${scopeLabel} · ${stageLabel}`)}<div class="form-actions"><button type="button" data-resume-refinement>${interfaceCopy("Resume refinement", "Reprendre l’affinement")}</button><button type="button" class="quiet-danger" data-cancel-refinement>${interfaceCopy("End this unfinished run", "Terminer ce processus inachevé")}</button></div>`;
      $("[data-resume-refinement]", resume).addEventListener("click", () => continueRefinement(active));
      $("[data-cancel-refinement]", resume).addEventListener("click", async () => {
        if (!await confirmAction(
          interfaceCopy("End this unfinished refinement?", "Terminer cet affinement inachevé ?"),
          interfaceCopy("Completed comparisons and title evidence stay saved, but this run's progress tracker will close.", "Les comparaisons et évaluations terminées restent enregistrées, mais le suivi de progression de ce processus sera fermé."),
          interfaceCopy("End run", "Terminer")
        )) return;
        await api(`/api/ratings/refinement-runs/${active.id}`, {method: "DELETE"});
        state.refinementRun = null;
        resume.hidden = true;
        choices.hidden = false;
      });
    }
    showMessage($("#refinement-scope-message"), "");
    openDialog($("#refinement-scope-dialog"));
  } catch (error) { toast(error.message); }
}

async function startRefinement(scope) {
  showMessage($("#refinement-scope-message"), scope === "full"
    ? interfaceCopy("Preparing the full-library refinement…", "Préparation de l’affinement de toute la bibliothèque…")
    : interfaceCopy("Preparing a focused refinement…", "Préparation d’un affinement ciblé…"));
  try {
    const run = await api("/api/ratings/refinement-runs", {method: "POST", body: JSON.stringify({scope})});
    await continueRefinement(run);
  } catch (error) { showMessage($("#refinement-scope-message"), error.message, true); }
}

async function startSingleTitleRefinement(entryId) {
  try {
    const run = await api("/api/ratings/refinement-runs", {method: "POST", body: JSON.stringify({scope: "focused", entry_id: entryId})});
    await continueRefinement(run);
  } catch (error) { toast(error.message); }
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
  nav.innerHTML = `<button class="quiet" data-page="1" ${page === 1 ? "disabled" : ""} aria-label="${esc(translatedText("First page"))}">«</button><button class="quiet" data-page="${page - 1}" ${page === 1 ? "disabled" : ""} aria-label="${esc(translatedText("Previous page"))}">‹</button>${pageButtons}<button class="quiet" data-page="${page + 1}" ${page === pages ? "disabled" : ""} aria-label="${esc(translatedText("Next page"))}">›</button><button class="quiet" data-page="${pages}" ${page === pages ? "disabled" : ""} aria-label="${esc(translatedText("Last page"))}">»</button><span class="page-summary">${esc(translatedText(`Page ${page} of ${pages} · ${total} titles`))}</span>`;
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
    const item = entry.catalog_item;
    $("#entry-id").value = entry.id;
    $("#entry-dialog-title").textContent = `${item.canonical_title}${item.release_year ? ` (${item.release_year})` : ""}`;
    const art = $("#entry-dialog-art");
    art.innerHTML = `${imageHtml(entryPoster(item), item.canonical_title, "poster", interfaceCopy(`Poster for ${item.canonical_title}`, `Affiche de ${item.canonical_title}`))}<div><span class="chip status-chip">${esc(statusLabel(entry.status))}</span><p>${esc(item.release_year || translatedText("Year unknown"))} · ${esc(mediaLabel(item.media_type))}</p></div>`;
    art.style.setProperty("--media-hue", titleHue(item.canonical_title));
    const entryDialog = $("#entry-dialog");
    const mediaArtwork = safeImageUrl(entryPoster(item));
    entryDialog.style.setProperty("--media-hue", titleHue(item.canonical_title));
    entryDialog.classList.toggle("has-media-art", Boolean(mediaArtwork));
    if (mediaArtwork) entryDialog.style.setProperty("--entry-art", `url(${JSON.stringify(mediaArtwork)})`);
    else entryDialog.style.removeProperty("--entry-art");
    bindPosterFallbacks(art);
    $("#entry-status").value = entry.status;
    $("#entry-rating").value = formatRatingInput(entry.personal_rating);
    $("#save-next-rating").hidden = !ratingReview;
    const moreActions = $(".more-actions", $("#entry-dialog"));
    if (moreActions) moreActions.open = false;
    $("#entry-started").value = entry.started_date || "";
    $("#entry-finished").value = entry.finished_date || "";
    $("#entry-watched").value = entry.watched_date || "";
    $("#entry-count").value = entry.view_count;
    const detailFacts = [
      ["Genres", entry.effective_genres.join(", ") || translatedText("Not available")],
      ["Subgenres", entry.effective_subgenres.join(", ") || translatedText("Not available")],
      ["Runtime", item.runtime_minutes ? `${item.runtime_minutes} min` : translatedText("Not available")],
      ["Community score", item.public_score != null ? `${item.public_score}/10` : translatedText("Not available")]
    ];
    $("#entry-overview-facts").innerHTML = `<div class="entry-fact-grid">${detailFacts.map(([label, fact]) => `<span><small>${esc(translatedText(label))}${label === "Community score" ? ` <i class="help-tip" tabindex="0" aria-label="${esc(translatedText("Community score help"))}" data-tip="${esc(translatedText("A provider community average for context only. It never changes your personal or technical rating."))}">?</i>` : ""}</small><strong translate="no">${esc(fact)}</strong></span>`).join("")}</div><div class="entry-description"><small>${esc(translatedText("Description"))}</small><p translate="no">${esc(item.overview || translatedText("No provider description is available yet."))}</p></div>`;
    bindHelpTips($("#entry-overview-facts"));
    $("#entry-tags").value = entry.user_tags.join(", ");
    $("#entry-notes").value = entry.notes || "";
    $("#entry-genre-add").value = entry.genre_additions.join(", ");
    $("#entry-genre-remove").value = entry.genre_removals.join(", ");
    $("#entry-subgenre-add").value = entry.subgenre_additions.join(", ");
    $("#entry-subgenre-remove").value = entry.subgenre_removals.join(", ");
    $("#delete-entry").hidden = Boolean(entry.deleted_at);
    $("#restore-entry").hidden = !entry.deleted_at;
    // Open the editor as soon as its essential controls are ready. Secondary
    // metadata should never prevent someone from restoring a deleted entry.
    selectEntryTab(initialTab);
    openDialog($("#entry-dialog"));
    $("#entry-metadata-query").value = entry.catalog_item.canonical_title;
    const verifiedIdentity = Boolean(entry.catalog_item.tmdb_movie_id || entry.catalog_item.tmdb_tv_id || entry.catalog_item.anilist_id || entry.catalog_item.mal_id || Object.keys(entry.catalog_item.external_ids || {}).length);
    // Imported entries already carry an explicit media type. Keep provider lookup
    // scoped to it so movie reviews do not hammer anime services and anime reviews
    // do not get buried under TMDb movie/TV matches.
    $("#entry-metadata-type").value = entry.catalog_item.media_type;
    const missing = [!entryPoster(entry.catalog_item) && "poster", !entry.catalog_item.release_year && "release date", !verifiedIdentity && "verified provider match", !entry.catalog_item.normalized_genres.length && "genres"].filter(Boolean);
    const missingLabels = {poster: "poster", "release date": "date de sortie", "verified provider match": "correspondance fournisseur vérifiée", genres: "genres"};
    $("#entry-metadata-state").textContent = verifiedIdentity
      ? (missing.length
        ? interfaceCopy(`Verified identity; missing ${missing.join(", ")}. Automatic refresh is safe for this entry.`, `Identité vérifiée ; éléments manquants : ${missing.map(value => missingLabels[value] || value).join(", ")}. L’actualisation automatique est sûre pour ce titre.`)
        : interfaceCopy(`${entry.catalog_item.provider_source || "Provider"} identity is verified.`, `Identité ${entry.catalog_item.provider_source || "fournisseur"} vérifiée.`))
      : interfaceCopy("Unresolved identity. Strong title/year matches may use popularity within a small result set; weak matches require your confirmation.", "Identité non résolue. Les correspondances solides de titre et d’année peuvent utiliser la popularité dans un petit ensemble de résultats ; les correspondances faibles exigent votre confirmation.");
    const origin = [entry.catalog_item.country, entry.catalog_item.language?.toUpperCase()].filter(Boolean).join(" · ");
    const facts = [["Type", mediaLabel(entry.catalog_item.media_type)], ["Format", providerFormatLabel(entry.catalog_item.provider_format)], ["Original title", entry.catalog_item.original_title && entry.catalog_item.original_title !== entry.catalog_item.canonical_title ? entry.catalog_item.original_title : null], ["Released", entry.catalog_item.release_date ? formatDate(entry.catalog_item.release_date) : entry.catalog_item.release_year], ["Runtime", entry.catalog_item.runtime_minutes ? `${entry.catalog_item.runtime_minutes} min` : null], ["Episodes", entry.catalog_item.episode_count], ["Origin / language", origin], ["Genres", entry.effective_genres.join(", ")], ["Subgenres", entry.effective_subgenres.join(", ")], ["Provider tags", entry.catalog_item.keywords.join(", ")], ["Community score", entry.catalog_item.public_score != null ? interfaceCopy(`${entry.catalog_item.public_score}/10 (not your rating)`, `${entry.catalog_item.public_score}/10 (pas votre note)`) : null], ["Provider", entry.catalog_item.provider_source?.replaceAll("_", " ")], ["Description", entry.catalog_item.overview]];
    $("#entry-metadata-facts").innerHTML = facts.filter(([, value]) => value).map(([label, value]) => `<span class="${label === "Description" ? "wide-fact" : ""}"><strong>${esc(translatedText(label))} :</strong> ${esc(value)}</span>`).join("");
    $("#entry-metadata-results").innerHTML = "";
    const context = entry.import_context || {};
    $("#entry-import-context").innerHTML = Object.keys(context).length ? `<details class="import-context"><summary>Imported source details</summary><dl>${Object.entries(context).map(([key, value]) => `<dt>${esc(key.replaceAll("_", " "))}</dt><dd>${esc(Array.isArray(value) ? value.join(", ") : value)}</dd>`).join("")}</dl></details>` : "";
    $("#viewing-history").innerHTML = entry.viewing_events.length ? entry.viewing_events.map(event => `<div class="viewing-row"><span>${esc(formatDate(event.viewed_on))} <small class="muted">${esc(viewingSourceLabel(event.source))}</small></span><button type="button" class="danger quiet-danger" data-event="${event.id}" data-event-date="${esc(formatDate(event.viewed_on))}" aria-label="Delete viewing on ${esc(formatDate(event.viewed_on))}">Delete</button></div>`).join("") : `<p class="muted">No individual viewing dates are stored. Aggregate view count may still be known.</p>`;
    $$("[data-event]", $("#viewing-history")).forEach(button => button.addEventListener("click", () => deleteViewing(entry.id, button.dataset.event, button.dataset.eventDate)));
    showMessage($("#entry-message"), "");
    if (initialTab === "metadata" && !verifiedIdentity) findEntryMetadata();
    if (initialTab === "releases") loadEntryReleases();
  } catch (error) { toast(error.message); }
}

async function openArtworkDialog() {
  const entry = state.currentEntry;
  if (!entry) return;
  const dialog = $("#artwork-dialog");
  const container = $("#artwork-options");
  $(".more-actions", $("#entry-dialog"))?.removeAttribute("open");
  $("#artwork-dialog-heading").textContent = `Choose image for ${entry.catalog_item.canonical_title}`;
  container.innerHTML = `<p class="muted">Loading available images…</p>`;
  showMessage($("#artwork-message"), "");
  state.artworkSelection = null;
  $("#save-media-image").disabled = true;
  openDialog(dialog);
  try {
    const data = await api(`/api/entries/${entry.id}/artwork`);
    if (!data.options.length) {
      container.innerHTML = `<div class="empty-state compact-empty"><h3>No provider images available</h3><p>Attach a verified metadata match with artwork support first.</p></div>`;
      if (data.warning) showMessage($("#artwork-message"), data.warning, true);
      $("#reset-media-image").disabled = !data.selected_url;
      return;
    }
    state.artworkSelection = data.selected_url;
    container.innerHTML = data.options.map((option, index) => `<label class="artwork-option ${option.poster_url === data.selected_url ? "selected" : ""}"><input type="radio" name="artwork-option" value="${esc(option.poster_url)}" ${option.poster_url === data.selected_url ? "checked" : ""}><span class="artwork-image">${imageHtml(option.poster_url, entry.catalog_item.canonical_title, "poster", `Alternative poster ${index + 1} for ${entry.catalog_item.canonical_title}`)}</span><span>${option.is_default ? "Provider default" : option.language ? option.language.toUpperCase() : "Text-free / other"}</span></label>`).join("");
    bindPosterFallbacks(container);
    $$("input[name='artwork-option']", container).forEach(input => input.addEventListener("change", event => {
      state.artworkSelection = event.currentTarget.value;
      $("#save-media-image").disabled = false;
      $$(".artwork-option", container).forEach(option => option.classList.toggle("selected", $("input", option).checked));
    }));
    $("#reset-media-image").disabled = !entry.catalog_item.poster_override_url;
    if (data.warning) showMessage($("#artwork-message"), data.warning, true);
  } catch (error) {
    container.innerHTML = "";
    showMessage($("#artwork-message"), error.message, true);
  }
}

async function saveArtworkSelection(posterUrl) {
  const entry = state.currentEntry;
  if (!entry) return;
  try {
    const updated = await api(`/api/entries/${entry.id}/artwork`, {method: "PUT", body: JSON.stringify({poster_url: posterUrl})});
    state.currentEntry = updated;
    $("#artwork-dialog").close();
    state.libraryLoaded = false;
    state.currentlyWatchingLoaded = false;
    state.rankingsLoaded = false;
    state.listsLoaded = false;
    await openEntry(entry.id);
    toast(posterUrl ? "Media image changed" : "Provider image restored");
    if (state.view === "library") await loadLibrary({preserveScroll: true, showSkeleton: false});
    if (state.view === "currently_watching") await loadCurrentlyWatching();
    if (state.view === "lists") await loadLists();
  } catch (error) { showMessage($("#artwork-message"), error.message, true); }
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
    state.libraryLoaded = false;
    state.currentlyWatchingLoaded = false;
    state.activeShowsLoaded = false;
    state.rankingsLoaded = false;
    state.listsLoaded = false;
    if (state.view === "library") await loadLibrary({preserveScroll: true, focusEntryId: id, showSkeleton: false});
    else if (state.view === "currently_watching") await loadCurrentlyWatching();
    else if (state.view === "active_shows") await loadActiveShows();
    else if (state.view === "rankings") await loadRankings();
    else if (state.view === "lists") await loadLists();
    else if (state.view === "insights") await loadInsights();
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
    openDialog(dialog);
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
    container.innerHTML = warnings + (data.results.length ? data.results.slice(0, 15).map((result, index) => `<div class="metadata-result">${imageHtml(result.poster_url, result.title)}<span><strong>${esc(result.title)}</strong>${result.original_title && result.original_title !== result.title ? `<small>${esc(result.original_title)}</small>` : ""}<small class="muted">${esc(result.year || translatedText("Year unknown"))} · ${esc(mediaLabel(result.media_type))}${result.provider_format ? ` · ${esc(providerFormatLabel(result.provider_format))}` : ""} · ${esc(result.provider.replaceAll("_", " "))}</small>${result.overview ? `<small>${esc(result.overview.slice(0, 180))}</small>` : ""}</span><button type="button" data-metadata-result="${index}">Attach this</button></div>`).join("") : `<p class="muted">No matches. Edit the title, search all types, or keep the current manual metadata.</p>`);
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
    button.textContent = translatedText(data.total ? `Review unresolved (${data.total})` : "No unresolved titles");
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
    button.textContent = translatedText(data.total ? `Review ratings (${data.total})` : "No ratings to review");
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
  $("#summary-cards").innerHTML = Array.from({length: 5}, () => `<article class="insight-overview-card skeleton-card"><div class="skeleton-lines"><span class="skeleton-block"></span><span class="skeleton-block"></span></div></article>`).join("");
  $("#insights-content").innerHTML = Array.from({length: 6}, () => `<section class="insight-panel skeleton-card"><div class="skeleton-lines"><span class="skeleton-block"></span><span class="skeleton-block"></span><span class="skeleton-block"></span></div></section>`).join("");
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

async function legacyLoadInsights() {
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

function insightQuery(overrides = {}) {
  const values = {...state.insightsFilters, ...overrides};
  if ((overrides.date_from || overrides.date_to) && !overrides.period) values.period = "custom";
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== "" && value != null && !(key === "watch_kind" && value === "all") && !(key === "aggregation" && value === "auto")) params.set(key, String(value));
  });
  return params;
}

function syncInsightsControls() {
  const filters = state.insightsFilters;
  $$('[data-insight-period]').forEach(button => {
    const active = button.dataset.insightPeriod === filters.period;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  $("#insights-custom-dates").hidden = filters.period !== "custom";
  const form = $("#insights-filter-form");
  ["date_from", "date_to", "media_type", "genre", "status", "watch_kind"].forEach(key => {
    if (form.elements[key]) form.elements[key].value = filters[key] || (key === "watch_kind" ? "all" : "");
  });
}

function renderInsightFilterChips() {
  const labels = {
    media_type: value => mediaLabel(value),
    genre: value => value,
    status: value => statusLabel(value),
    watch_kind: value => ({first: "First watches", rewatch: "Rewatches"})[value] || value
  };
  const chips = Object.entries(labels).filter(([key]) => state.insightsFilters[key] && !(key === "watch_kind" && state.insightsFilters[key] === "all"));
  $("#insights-filter-chips").innerHTML = chips.length
    ? `${chips.map(([key, formatter]) => `<button type="button" class="filter-chip" data-clear-insight-filter="${key}">${esc(translatedText(formatter(state.insightsFilters[key])))} <span aria-hidden="true">×</span></button>`).join("")}<button type="button" class="text-button" data-reset-insight-filters>Reset filters</button>`
    : "";
  $$('[data-clear-insight-filter]').forEach(button => button.addEventListener("click", () => {
    const key = button.dataset.clearInsightFilter;
    state.insightsFilters[key] = key === "watch_kind" ? "all" : "";
    syncInsightsControls();
    scheduleInsightsLoad(0);
  }));
  $("[data-reset-insight-filters]")?.addEventListener("click", () => {
    state.insightsFilters = {period: "year", date_from: "", date_to: "", media_type: "", genre: "", status: "", watch_kind: "all", aggregation: "auto"};
    syncInsightsControls();
    scheduleInsightsLoad(0);
  });
}

function insightDelta(current, previous, {rating = false, hours = false} = {}) {
  if (previous == null || current == null) return "";
  const change = Number(current) - Number(previous);
  const sign = change > 0 ? "+" : "";
  const value = rating ? change.toFixed(1) : hours ? change.toFixed(1) : formatInteger(change);
  return `<small class="insight-delta ${change > 0 ? "positive" : change < 0 ? "negative" : ""}">${sign}${value} ${esc(translatedText("vs previous period"))}</small>`;
}

function insightOverviewCard(value, label, delta, detail = "") {
  return `<article class="insight-overview-card"><span>${esc(translatedText(label))}</span><strong>${esc(value)}</strong>${delta}${detail ? `<small>${esc(translatedText(detail))}</small>` : ""}</article>`;
}

function localizedInsightCallout(callout) {
  if (state.interfaceLanguage !== "fr") {
    return {title: translatedText(callout.title), detail: translatedText(callout.detail)};
  }
  if (callout.kind === "peak_activity") {
    return {
      title: "Votre période la plus active",
      detail: `${countText(callout.title_count, "title", "titles", "titre", "titres")} et ${countText(callout.episode_count, "episode", "episodes", "épisode", "épisodes")} enregistrés.`
    };
  }
  if (callout.kind === "favourite_genre") {
    return {
      title: "Un favori solidement étayé",
      detail: `${Number(callout.average_rating).toLocaleString(interfaceLocale(), {maximumFractionDigits: 2})}/10 sur ${countText(callout.rated_count, "rated title", "rated titles", "titre noté", "titres notés")}.`
    };
  }
  if (callout.kind === "unrated") {
    return {
      title: "Les notes peuvent préciser votre profil",
      detail: `${countText(callout.title_count, "title", "titles", "titre", "titres")} sans note personnelle dans cette sélection.`
    };
  }
  if (callout.kind === "rewatch") {
    return {
      title: "Titres que vous avez revus",
      detail: `${countText(callout.title_count, "title", "titles", "titre", "titres")} avec plusieurs visionnages dans cette sélection.`
    };
  }
  return {title: translatedText(callout.title), detail: translatedText(callout.detail)};
}

function registerInsightDrilldown(query, title) {
  const id = `insight-${state.insightDrilldowns.size + 1}`;
  state.insightDrilldowns.set(id, {query, title});
  return id;
}

function insightBarRows(rows, {label, value, display, query, title, empty = "Not enough matching data yet."}) {
  if (!rows.length) return `<p class="empty-chart muted">${esc(translatedText(empty))}</p>`;
  const maximum = Math.max(...rows.map(row => Number(value(row) || 0)), 1);
  return `<div class="insight-bars">${rows.map(row => { const amount = Number(value(row) || 0); const drilldown = registerInsightDrilldown(query(row), title(row)); return `<button type="button" class="insight-bar-row" data-insight-drilldown="${drilldown}"><span>${esc(translatedText(label(row)))}</span><span class="insight-bar-track"><span style="width:${Math.max(amount / maximum * 100, amount ? 2 : 0).toFixed(2)}%"></span></span><strong>${esc(display(row))}</strong></button>`; }).join("")}</div>`;
}

function renderDateFreeInsight(data) {
  const root = $("#insight-activity-chart");
  const items = data.date_free_activity?.items || [];
  if (!root || !items.length) {
    if (root) root.innerHTML = `<div class="empty-state compact-empty"><h3>${esc(translatedText("No release-year data in this scope"))}</h3><p>${esc(translatedText("Add or verify release years to reveal this alternate view."))}</p></div>`;
    return;
  }
  const maximum = Math.max(...items.map(item => Number(item.titles || 0)), 1);
  root.innerHTML = `<div class="activity-chart-scroll"><div class="insight-era-chart" role="group" aria-label="${esc(translatedText("Watched titles by release era"))}">${items.map((item, index) => `<button type="button" data-release-era="${index}" aria-label="${esc(`${translatedText(item.key)}: ${countText(item.titles, "title", "titles", "titre", "titres")}`)}"><strong>${formatInteger(item.titles)}</strong><i style="height:${Math.max(Number(item.titles || 0) / maximum * 100, 4)}%"></i><span>${esc(translatedText(item.key))}</span></button>`).join("")}</div></div>`;
  $$('[data-release-era]', root).forEach(button => button.addEventListener("click", () => {
    const item = items[Number(button.dataset.releaseEra)];
    const query = {period: "all", date_from: "", date_to: "", activity_only: true};
    if (item.release_year_unknown) query.release_year_unknown = true;
    else {
      query.release_year_from = item.release_year_from;
      query.release_year_to = item.release_year_to;
    }
    openInsightDrilldown(query, item.key);
  }));
}

function renderInsightActivity(data, metric = "titles") {
  const root = $("#insight-activity-chart");
  if (!root) return;
  const items = data.activity.items;
  if (!items.length) {
    if ($("#insight-date-free-toggle")?.checked) {
      renderDateFreeInsight(data);
      return;
    }
    const hint = data.date_free_activity?.items?.length
      ? "Turn on “No watch dates?” above to explore release eras, or add exact viewing dates."
      : "Try a broader date range or add exact viewing dates.";
    root.innerHTML = `<div class="empty-state compact-empty"><h3>${esc(translatedText("No dated activity in this scope"))}</h3><p>${esc(translatedText(hint))}</p></div>`;
    return;
  }
  const values = items.map(item => Number(item[metric] || 0));
  const maximum = Math.max(...values, 1);
  const width = Math.max(620, items.length * 54);
  const chartHeight = 220;
  const points = items.map((item, index) => {
    const x = 34 + index * ((width - 68) / Math.max(items.length - 1, 1));
    const y = chartHeight - 30 - (Number(item[metric] || 0) / maximum) * 150;
    return {item, x, y};
  });
  const metricLabels = {titles: ["title", "titles", "titre", "titres"], episodes: ["episode", "episodes", "épisode", "épisodes"], estimated_hours: ["estimated hour", "estimated hours", "heure estimée", "heures estimées"]};
  root.innerHTML = `<div class="activity-chart-scroll"><svg class="activity-line-chart" viewBox="0 0 ${width} ${chartHeight}" role="img" aria-label="${esc(translatedText("Viewing activity over time"))}"><path class="activity-area" d="M ${points[0].x} ${chartHeight - 30} ${points.map(point => `L ${point.x} ${point.y}`).join(" ")} L ${points.at(-1).x} ${chartHeight - 30} Z"></path><path class="activity-line" d="${points.map((point, index) => `${index ? "L" : "M"} ${point.x} ${point.y}`).join(" ")}"></path>${points.map((point, index) => { const labels = metricLabels[metric] || metricLabels.titles; return `<g><circle cx="${point.x}" cy="${point.y}" r="5" tabindex="0" role="button" data-activity-point="${index}" aria-label="${esc(`${point.item.key}: ${countText(point.item[metric], ...labels)}`)}"></circle><text x="${point.x}" y="${chartHeight - 9}" text-anchor="middle">${esc(point.item.key)}</text></g>`; }).join("")}</svg></div>`;
  const openPoint = point => {
    const item = items[Number(point.dataset.activityPoint)];
    openInsightDrilldown({period: "custom", date_from: item.date_from, date_to: item.date_to}, item.key);
  };
  $$('[data-activity-point]', root).forEach(point => {
    point.addEventListener("click", () => openPoint(point));
    point.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openPoint(point);
      }
    });
  });
}

function renderInsights(data) {
  state.insightDrilldowns.clear();
  const summary = data.summary;
  const previous = data.previous_summary;
  $("#summary-cards").innerHTML = [
    insightOverviewCard(formatInteger(summary.titles_watched), "Titles watched", previous ? insightDelta(summary.titles_watched, previous.titles_watched) : ""),
    insightOverviewCard(formatInteger(summary.episodes_watched), "Episodes watched", previous ? insightDelta(summary.episodes_watched, previous.episodes_watched) : ""),
    insightOverviewCard(`${Number(summary.estimated_hours || 0).toLocaleString(interfaceLocale(), {maximumFractionDigits: 1})}h`, "Estimated watch time", previous ? insightDelta(summary.estimated_hours, previous.estimated_hours, {hours: true}) : "", countText(summary.estimated_event_count, "viewing record had known runtime", "viewing records had known runtimes", "enregistrement avait une durée connue", "enregistrements avaient une durée connue")),
    insightOverviewCard(formatRating(summary.average_rating), "Average personal rating", previous ? insightDelta(summary.average_rating, previous.average_rating, {rating: true}) : ""),
    insightOverviewCard(formatInteger(summary.rewatches), "Repeat viewings", previous ? insightDelta(summary.rewatches, previous.rewatches) : "")
  ].join("");

  const ratingItems = data.ratings.items.filter(item => item.count);
  const ratingMax = Math.max(...ratingItems.map(item => item.count), 1);
  const histogram = ratingItems.length ? `<div class="insight-rating-histogram" aria-label="${esc(translatedText("Personal rating distribution"))}">${ratingItems.map(item => { const key = registerInsightDrilldown({rating_bucket: item.rating, activity_only: true}, `${formatRating(item.rating)} ratings`); return `<button type="button" data-insight-drilldown="${key}" aria-label="${esc(`${countText(item.count, "title", "titles", "titre", "titres")} · ${translatedText("Rating")} ${formatRating(item.rating)}`)}"><span>${formatInteger(item.count)}</span><i style="height:${Math.max(item.count / ratingMax * 100, 4)}%"></i><small>${formatRating(item.rating)}</small></button>`; }).join("")}</div>` : `<p class="empty-chart muted">${esc(translatedText("Rate titles to reveal your distribution."))}</p>`;
  const genres = data.genres.slice(0, 8);
  const mediaBars = insightBarRows(data.media_types, {label: row => mediaLabel(row.value), value: row => row.count, display: row => formatInteger(row.count), query: row => ({media_type: row.value}), title: row => mediaLabel(row.value)});
  const statusBars = insightBarRows(data.statuses, {label: row => statusLabel(row.value), value: row => row.count, display: row => formatInteger(row.count), query: row => ({status: row.value}), title: row => statusLabel(row.value)});
  const genreBars = insightBarRows(genres, {label: row => row.genre, value: row => row.average_rating || 0, display: row => row.average_rating == null ? "—" : `${formatRating(row.average_rating)} · ${row.rated_count}`, query: row => ({genre: row.genre, activity_only: true}), title: row => row.genre, empty: "Add ratings and genre metadata to reveal supported favourites."});
  const callouts = data.callouts.length ? data.callouts.map(callout => { const key = registerInsightDrilldown(callout.drilldown, callout.value || callout.title); const copy = localizedInsightCallout(callout); return `<article class="insight-callout"><p class="eyebrow">${esc(copy.title)}</p><h3 translate="no">${esc(callout.value)}</h3><p>${esc(copy.detail)}</p><button type="button" class="text-button" data-insight-drilldown="${key}">${esc(translatedText("View titles"))} →</button></article>`; }).join("") : `<div class="empty-state compact-empty"><h3>${esc(translatedText("Patterns will appear as your history grows"))}</h3><p>${esc(translatedText("Add viewing dates, ratings, and verified genres to strengthen these callouts."))}</p></div>`;
  const coverage = data.coverage.timeline_coverage == null ? "—" : formatRate(data.coverage.timeline_coverage);
  const coverageCopy = `${formatInteger(data.coverage.dated_events)} ${translatedText("dated")} · ${formatInteger(data.coverage.undated_events)} ${translatedText("undated")} · ${coverage} ${translatedText("timeline coverage")}`;
  const dateFreeAvailable = !data.activity.items.length && Boolean(data.date_free_activity?.items?.length);
  const activityControls = dateFreeAvailable
    ? `<label class="no-date-visual-toggle"><input id="insight-date-free-toggle" type="checkbox" role="switch"><span><strong>${esc(translatedText("No watch dates?"))}</strong><small>${esc(translatedText("Show release-year view"))}</small></span></label>`
    : `<label>${esc(translatedText("Measure"))}<select id="insight-activity-metric"><option value="titles">${esc(translatedText("Titles"))}</option><option value="episodes">${esc(translatedText("Episodes"))}</option><option value="estimated_hours">${esc(translatedText("Estimated hours"))}</option></select></label><label>${esc(translatedText("Group by"))}<select id="insight-aggregation"><option value="auto">${esc(translatedText("Automatic"))}</option><option value="week">${esc(translatedText("Week"))}</option><option value="month">${esc(translatedText("Month"))}</option><option value="year">${esc(translatedText("Year"))}</option></select></label>`;

  $("#insights-content").innerHTML = `<section class="insight-panel insight-activity-panel"><div class="viz-heading"><div><p class="eyebrow">${esc(translatedText("Activity"))}</p><h3 id="insight-activity-heading">${esc(translatedText("Viewing over time"))}</h3></div><div class="viz-controls">${activityControls}</div></div><div id="insight-activity-chart"></div><p id="insight-activity-note" class="chart-note">${esc(coverageCopy)}</p></section>
    <section class="insight-panel"><div class="viz-heading"><div><p class="eyebrow">${esc(translatedText("Taste"))}</p><h3>${esc(translatedText("Your rating curve"))}</h3></div><strong>${formatRating(data.ratings.median)} ${esc(translatedText("median"))}</strong></div>${histogram}<p class="chart-note">${formatRating(data.ratings.average)} ${esc(translatedText("average"))} · ${formatInteger(data.ratings.unrated_count)} ${esc(translatedText("unrated"))}</p></section>
    <section class="insight-panel"><p class="eyebrow">${esc(translatedText("Taste"))}</p><h3>${esc(translatedText("Genre ratings"))}</h3>${genreBars}<p class="chart-note">${esc(translatedText("Shown averages are raw personal ratings. Ordering adds a small confidence adjustment; at least 3 rated titles are required for a favourite callout."))}</p></section>
    <section class="insight-panel"><p class="eyebrow">${esc(translatedText("Library mix"))}</p><h3>${esc(translatedText("Media types"))}</h3>${mediaBars}</section>
    <section class="insight-panel"><p class="eyebrow">${esc(translatedText("Library mix"))}</p><h3>${esc(translatedText("Statuses"))}</h3>${statusBars}</section>
    <section class="insight-panel insight-patterns"><p class="eyebrow">${esc(translatedText("Patterns worth noticing"))}</p><div class="insight-callout-grid">${callouts}</div></section>
    <details class="insight-definitions"><summary>${esc(translatedText("How these insights are calculated"))}</summary><dl>${Object.values(data.definitions).map(value => `<div><dd>${esc(translatedText(value))}</dd></div>`).join("")}</dl></details>`;
  const aggregationControl = $("#insight-aggregation");
  if (aggregationControl) {
    aggregationControl.value = state.insightsFilters.aggregation;
    aggregationControl.addEventListener("change", event => { state.insightsFilters.aggregation = event.currentTarget.value; scheduleInsightsLoad(0); });
  }
  $("#insight-activity-metric")?.addEventListener("change", event => renderInsightActivity(data, event.currentTarget.value));
  $("#insight-date-free-toggle")?.addEventListener("change", event => {
    const alternate = event.currentTarget.checked;
    $("#insight-activity-heading").textContent = translatedText(alternate ? "Library by release era" : "Viewing over time");
    $("#insight-activity-note").textContent = alternate
      ? translatedText("Release years describe the titles, not when you watched them. Select an era to inspect its titles.")
      : coverageCopy;
    renderInsightActivity(data);
  });
  $$('[data-insight-drilldown]', $("#insights-content")).forEach(button => button.addEventListener("click", () => {
    const target = state.insightDrilldowns.get(button.dataset.insightDrilldown);
    if (target) openInsightDrilldown(target.query, target.title);
  }));
  renderInsightActivity(data);
  localizeTree($("#summary-cards"));
  localizeTree($("#insights-content"));
}

async function openInsightDrilldown(overrides, title) {
  const panel = $("#insights-drawer");
  const list = $("#insights-drawer-list");
  panel.hidden = false;
  $("#insights-drawer-title").textContent = translatedText(title || "Details");
  list.innerHTML = librarySkeletons();
  try {
    const data = await api(`/api/insights/titles?${insightQuery(overrides)}`);
    list.innerHTML = data.items.length ? data.items.map(entry => { const item = entry.catalog_item; return `<article class="insight-title-row" data-entry="${entry.id}">${imageHtml(entryPoster(item), item.canonical_title, "poster", interfaceCopy(`Poster for ${item.canonical_title}`, `Affiche de ${item.canonical_title}`))}<div><h4 translate="no">${esc(item.canonical_title)}</h4><p>${esc(item.release_year || translatedText("Year unknown"))} · ${esc(mediaLabel(item.media_type))} · ${entry.personal_rating == null ? translatedText("Unrated") : formatRating(entry.personal_rating)}</p><small>${countText(entry.scope_title_viewings, "title viewing", "title viewings", "visionnage du titre", "visionnages du titre")} · ${countText(entry.scope_episode_viewings, "episode", "episodes", "épisode", "épisodes")}${entry.scope_dates.length ? ` · ${esc(entry.scope_dates.slice(0, 3).map(formatDate).join(", "))}` : ""}</small></div><button type="button" class="quiet" data-open-insight-title>${esc(translatedText("Open title"))}</button></article>`; }).join("") : `<div class="empty-state compact-empty"><h3>${esc(translatedText("No matching titles"))}</h3><p>${esc(translatedText("This result may depend on activity records that do not identify a dated title in the selected period."))}</p></div>`;
    $$('[data-open-insight-title]', list).forEach(button => button.addEventListener("click", () => openEntry(button.closest("[data-entry]").dataset.entry)));
    bindPosterFallbacks(list);
  } catch (error) { list.innerHTML = `<p class="message error">${esc(error.message)}</p>`; }
}

function scheduleInsightsLoad(delay = 180) {
  clearTimeout(state.insightsTimer);
  state.insightsTimer = setTimeout(() => {
    persistNavigationState();
    loadInsights();
  }, delay);
}

async function loadInsights() {
  state.insightsController?.abort();
  state.insightsController = new AbortController();
  syncInsightsControls();
  renderInsightFilterChips();
  showMessage($("#insights-state"), translatedText("Calculating insights…"));
  insightsSkeletons();
  try {
    const data = await api(`/api/insights?${insightQuery()}`, {signal: state.insightsController.signal});
    renderInsights(data);
    $("#insights-updated").textContent = `${translatedText("Updated")} ${new Date().toLocaleTimeString(interfaceLocale(), {hour: "2-digit", minute: "2-digit"})}`;
    showMessage($("#insights-state"), "");
  } catch (error) {
    if (error.name === "AbortError") return;
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
    state.listsLoaded = false;
    if (data.duplicate) await openEntry(data.entry.id);
    await loadLibrary({focusEntryId: state.view === "library" ? data.entry.id : null});
    if (state.view === "lists") await loadLists();
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
    state.listsLoaded = false;
    await loadLibrary();
    if (state.view === "insights") await loadInsights();
    if (data.status !== "already_imported" && $("#enrich-after-import").checked) await startEnrichment();
  } catch (error) { showMessage($("#import-message"), error.message, true); }
}

function localizedMetadataStatusText(value) {
  if (state.interfaceLanguage !== "fr" || !value) return translatedText(value || "");
  let match = String(value).match(/^Checking (.+)$/);
  if (match) return `Vérification de ${match[1]}`;
  match = String(value).match(/^Resolved or refreshed (\d+) entr(?:y|ies); (\d+) unresolved need confirmation; (\d+) failed\.$/);
  if (match) return `${match[1]} titre${match[1] === "1" ? " résolu ou actualisé" : "s résolus ou actualisés"} ; ${match[2]} non résolu${match[2] === "1" ? " exige" : "s exigent"} une confirmation ; ${match[3]} échec${match[3] === "1" ? "" : "s"}.`;
  match = String(value).match(/^(.+) search is temporarily unavailable\.$/);
  if (match) return `La recherche ${match[1]} est temporairement indisponible.`;
  match = String(value).match(/^(.+) is temporarily unavailable\.$/);
  if (match) return `${match[1]} est temporairement indisponible.`;
  return translatedText(value);
}

function renderEnrichmentStatus(data) {
  const previous = state.enrichmentStatus;
  state.enrichmentStatus = data.status;
  const running = data.status === "running";
  const total = Number(data.total || 0);
  const processed = Number(data.processed || 0);
  const detail = localizedMetadataStatusText(data.message || (data.status === "idle" ? "No metadata fill has run yet." : ""));
  const warningText = (data.warnings || []).map(localizedMetadataStatusText).join(" ");
  const reasonLabels = {no_results: "no results", ambiguous: "ambiguous", conflicting_year_or_type: "conflicting year/type", duplicate_identity: "duplicate identity", detail_failure: "detail failure", provider_outage: "provider outage"};
  const reasonText = Object.entries(data.skip_reasons || {}).filter(([, count]) => count).map(([reason, count]) => `${count} ${translatedText(reasonLabels[reason] || reason)}`).join(", ");
  const matchLabels = {stable_provider_id: "stable provider ID", exact_title: "exact title", exact_alias: "exact alias", strong_title_prefix: "strong title prefix", single_compatible_candidate: "single compatible result"};
  const matchText = Object.entries(data.match_reasons || {}).filter(([, count]) => count).map(([reason, count]) => `${count} ${translatedText(matchLabels[reason] || reason)}`).join(", ");
  const progressText = total ? (state.interfaceLanguage === "fr"
    ? ` ${processed}/${total} vérifiés ; ${data.enriched} actualisés, ${data.needs_confirmation || 0} à confirmer, ${data.failed} en échec.`
    : ` ${processed}/${total} checked; ${data.enriched} refreshed, ${data.needs_confirmation || 0} need confirmation, ${data.failed} failed.`) : "";
  const matchedText = matchText ? interfaceCopy(` Matched by: ${matchText}.`, ` Correspondances : ${matchText}.`) : "";
  const unresolvedText = reasonText ? interfaceCopy(` Unresolved: ${reasonText}.`, ` Non résolus : ${reasonText}.`) : "";
  $("#enrichment-status").textContent = `${detail}${progressText}${matchedText}${unresolvedText} ${warningText}`.trim();
  $("#enrichment-progress").hidden = !running && !total;
  $("#enrichment-progress").max = Math.max(total, 1);
  $("#enrichment-progress").value = Math.min(processed, Math.max(total, 1));
  $("#start-enrichment").disabled = running;
  $("#start-enrichment").textContent = running ? "Resolving metadata…" : "Resolve & refresh";
  const banner = $("#enrichment-banner");
  clearTimeout(state.enrichmentBannerTimer);
  const justFinished = previous === "running" && data.status !== "running";
  banner.hidden = data.status === "idle" || (!running && !justFinished);
  $("#enrichment-banner-text").textContent = `${translatedText(running ? "Metadata fill running." : "Metadata fill finished.")} ${detail}${progressText}${matchedText}${unresolvedText} ${warningText}`.trim();
  if (justFinished) state.enrichmentBannerTimer = setTimeout(() => { banner.hidden = true; }, 10000);
  if (previous === "running" && data.status !== "running") {
    loadLibrary({preserveScroll: true, showSkeleton: false});
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

function renderServerReadiness(data) {
  state.accessMode = data.mode || state.accessMode;
  const active = state.accessMode === "server";
  $("#access-mode-title").textContent = translatedText("Standalone PMT Server Beta");
  $("#access-mode-chip").textContent = translatedText(active ? "Server running" : "Server stopped");
  $("#access-mode-chip").classList.toggle("success-chip", active);
  $("#access-mode-copy").textContent = translatedText("This console belongs to the separate server installation. Personal PMT applications connect to it without becoming server administrators.");
  $("#server-runtime-state").textContent = translatedText(data.local_only_blocked_reason || "Tailscale availability is separate from the local PMT Server process.");
  const serverToggle = $("#server-mode-toggle");
  serverToggle.checked = active;
  serverToggle.disabled = true;
  $("#remote-server-client").hidden = active;
  if ($(".server-package-card")) $(".server-package-card").hidden = active;
  $("#server-readiness").hidden = !active;
  $("#active-server-actions").hidden = !active;
  $("#server-access-url").textContent = active && data.access_url ? interfaceCopy(`Access URL: ${data.access_url}`, `Adresse d’accès : ${data.access_url}`) : "";
  if ($("#server-owner-address")) $("#server-owner-address").textContent = active && data.access_url ? data.access_url : "Server address unavailable";
  $("#server-last-connection").textContent = data.last_connection_at
    ? new Date(data.last_connection_at).toLocaleString(interfaceLocale())
    : translatedText("No authenticated browser yet");
  const backupWhen = data.last_backup_at
    ? new Date(data.last_backup_at).toLocaleString(interfaceLocale())
    : translatedText("No scheduled backup yet");
  $("#server-backup-status").textContent = `${backupWhen} · ${translatedText(String(data.backup_status || "not started").replaceAll("_", " "))}`;
  $("#server-readiness").innerHTML = (data.checks || []).map(item => `
    <div class="readiness-item ${item.ok ? "pass" : ""}"><span class="status-dot" aria-hidden="true"></span><strong>${esc(translatedText(item.ok ? "Check passed" : "Needs attention"))} · ${esc(translatedText(item.label))}</strong><small>${esc(translatedText(item.ok ? "This requirement is ready." : item.remediation))}</small></div>`).join("");
}

async function changeServerMode(event) {
  const toggle = event.currentTarget;
  if (state.accessMode !== "local") {
    toggle.checked = true;
    toast("Use the standalone server controls on the server device.");
    return;
  }
  const active = state.remoteServerProfiles.find(profile => profile.enabled);
  const saved = state.remoteServerProfiles[0];
  if (!toggle.checked && active) {
    const confirmed = await confirmAction(
      "Disconnect this application from PMT Server?",
      "This device returns to its separate local library. The server account, server library, shared lists, and backups stay unchanged, and you can reconnect without re-entering the password while the saved device session remains valid.",
      "Disconnect this app"
    );
    if (!confirmed) { toggle.checked = true; return; }
    await api(`/api/device/server-connections/${active.id}`, {method: "PATCH", body: JSON.stringify({enabled: false})});
    toast("Server connection paused; your server account was not deleted");
    await loadDeviceServerConnections();
    return;
  }
  if (toggle.checked && saved) {
    try {
      await api(`/api/device/server-connections/${saved.id}`, {method: "PATCH", body: JSON.stringify({enabled: true})});
      await api(`/api/device/server-connections/${saved.id}/sync`, {method: "POST", body: "{}"});
      toast("PMT Server reconnected with the saved device session");
      await openDeviceServerAccount(saved.id);
    } catch (error) {
      toast(error.message);
    }
    await loadDeviceServerConnections();
    return;
  }
  toggle.checked = false;
  $("#remote-server-wizard")?.setAttribute("open", "");
  $("#remote-server-client")?.scrollIntoView({behavior: "smooth", block: "center"});
}

async function loadServerReadiness() {
  if (state.accessMode === "local") {
    await loadDeviceServerConnections();
    return;
  }
  const data = await api("/api/server/readiness");
  renderServerReadiness(data);
  await loadServerAccounts();
}

function renderDeviceConnectionState(items) {
  state.remoteServerProfiles = items;
  const active = items.find(profile => profile.enabled);
  const saved = items[0];
  const toggle = $("#server-mode-toggle");
  toggle.checked = Boolean(active);
  toggle.disabled = !saved;
  // The local application never exposes account navigation. When a saved PMT
  // Server connection is opened, its authenticated server UI supplies the
  // account control; the separate local library remains account-free.
  $("#open-account").hidden = true;
  $("#access-mode-title").textContent = translatedText("PMT Server Beta");
  $("#access-mode-chip").textContent = translatedText(active ? "Server detected" : saved ? "Disconnected" : "Not detected");
  $("#access-mode-chip").classList.toggle("success-chip", Boolean(active));
  $("#access-mode-copy").textContent = active
    ? interfaceCopy(
      `Connected to ${active.label} as @${active.account_username}. The saved device session is checked automatically when PMT opens.`,
      `Connecté à ${active.label} avec le compte @${active.account_username}. La session enregistrée de cet appareil est vérifiée automatiquement à l’ouverture de PMT.`,
      `已作为 @${active.account_username} 连接到 ${active.label}。PMT 启动时会自动检查此设备保存的会话。`
    )
    : saved
      ? interfaceCopy(
        `Connection to ${saved.label} is paused. This application is using its separate local library; the server account and library remain unchanged.`,
        `La connexion à ${saved.label} est suspendue. Cette application utilise sa bibliothèque locale distincte ; le compte et la bibliothèque du serveur restent inchangés.`,
        `与 ${saved.label} 的连接已暂停。此应用正在使用独立的本地媒体库；服务器账户和媒体库保持不变。`
      )
      : translatedText("Not connected. This application is using its private local library.");
  $("#server-runtime-state").textContent = translatedText(active
    ? "If Tailscale or the server is offline, pending changes remain safe and PMT reports the connection as temporarily unavailable."
    : saved
      ? "Turn the switch on to reconnect with the securely saved device session."
      : "Set up the separate PMT Server Beta, then paste its one-time invitation link below.");
  $("#server-readiness").hidden = true;
  $("#active-server-actions").hidden = true;
  $("#remote-server-client").hidden = false;
  if ($(".server-package-card")) $(".server-package-card").hidden = false;
}

function renderDeviceServerConnections(items) {
  renderDeviceConnectionState(items);
  const container = $("#remote-server-connections");
  if (!items.length) {
    container.innerHTML = `<p class="muted">No server is connected to this device yet.</p>`;
    return;
  }
  container.innerHTML = items.map(profile => `
    <article class="integration-card" data-remote-profile="${esc(profile.id)}">
      <div><strong>${esc(profile.label)} <span class="status-badge">${esc(translatedText(profile.enabled ? "Connected" : "Disconnected"))}</span></strong><p class="muted">${esc(profile.base_url)} · @${esc(profile.account_username)}</p><p class="muted">${profile.last_synced_at ? `Last synced ${esc(new Date(profile.last_synced_at).toLocaleString(interfaceLocale()))}` : "Ready for first sync"} · ${profile.cached_entry_count} cached · ${profile.pending_count} queued${profile.conflict_count ? ` · ${profile.conflict_count} need review` : ""}</p></div>
      <div class="metadata-actions">${profile.enabled ? `<button type="button" class="quiet" data-remote-action="open" data-profile-id="${esc(profile.id)}">${esc(translatedText("Open account"))}</button>` : ""}${profile.conflict_count ? `<button type="button" class="warning" data-remote-action="review" data-profile-id="${esc(profile.id)}">Review ${profile.conflict_count}</button>` : ""}<button type="button" data-remote-action="${profile.enabled ? "pause" : "resume"}" data-profile-id="${esc(profile.id)}">${esc(translatedText(profile.enabled ? "Disconnect this app" : "Reconnect"))}</button><button type="button" class="quiet-danger" data-remote-action="forget" data-profile-id="${esc(profile.id)}">Forget</button></div>
    </article>`).join("");
}

async function openDeviceServerAccount(profileId) {
  const session = await api(`/api/device/server-connections/${profileId}/browser-session`, {method: "POST", body: "{}"});
  const query = new URLSearchParams({client_return: window.location.origin});
  const desktop = new URLSearchParams(window.location.search).get("desktop");
  if (desktop) query.set("desktop", desktop);
  const fragment = new URLSearchParams({"native-session": session.handoff_token});
  window.location.assign(`${String(session.server_url).replace(/\/$/, "")}/?${query}#${fragment}`);
}

function remoteChangeLabel(item) {
  const labels = {"entry.patch": "Title details", "list.patch": "List details", "list.item.add": "Add list title", "list.item.remove": "Remove list title"};
  return labels[item.operation] || "Queued change";
}

async function reviewDeviceServerConflicts(profileId) {
  const panel = $("#remote-server-conflicts");
  panel.hidden = false;
  panel.innerHTML = `<p class="muted">Loading conflicts…</p>`;
  const data = await api(`/api/device/server-connections/${profileId}/outbox`);
  const conflicts = (data.items || []).filter(item => item.state === "conflict");
  if (!conflicts.length) {
    panel.innerHTML = `<div class="section-heading"><div><strong>No conflicts need review</strong><p class="muted">The server and this device are in agreement.</p></div><button type="button" class="quiet" data-close-remote-conflicts>Close</button></div>`;
    return;
  }
  panel.innerHTML = `<div class="section-heading"><div><strong>Choose which edit to keep</strong><p class="muted">Nothing is overwritten automatically. “Keep server” discards only this device’s queued edit; “Retry my edit” applies it to the newest version.</p></div><button type="button" class="quiet" data-close-remote-conflicts>Close</button></div><div class="integration-list">${conflicts.map(item => `<article class="integration-card"><div><strong>${esc(remoteChangeLabel(item))}</strong><p class="muted">Queued ${esc(new Date(item.client_timestamp).toLocaleString(interfaceLocale()))} · ${esc(Object.keys(item.payload || {}).join(", ") || "list membership")}</p></div><div class="metadata-actions"><button type="button" class="quiet" data-remote-conflict-action="discard" data-profile-id="${esc(profileId)}" data-request-id="${esc(item.request_id)}">Keep server</button><button type="button" data-remote-conflict-action="rebase" data-profile-id="${esc(profileId)}" data-request-id="${esc(item.request_id)}">Retry my edit</button></div></article>`).join("")}</div>`;
}

async function loadDeviceServerConnections() {
  $("#remote-server-client").hidden = state.accessMode !== "local";
  if (state.accessMode !== "local") return;
  const data = await api("/api/device/server-connections");
  renderDeviceServerConnections(data.items || []);
}

async function autoConnectSavedServer() {
  try {
    const connections = await api("/api/device/server-connections");
    renderDeviceServerConnections(connections.items || []);
    if (!(connections.items || []).some(profile => profile.enabled)) return;
    const result = await api("/api/device/server-connections/sync-enabled", {method: "POST", body: "{}"});
    const failed = (result.items || []).find(item => !item.ok);
    if (failed) {
      $("#server-runtime-state").textContent = translatedText("The saved server is temporarily unreachable. Your local library and queued changes remain available.");
      return;
    }
    await loadDeviceServerConnections();
  } catch (_) {
    // Local PMT remains usable when Tailscale or the standalone server is offline.
  }
}

function renderPersonalTailscale(data) {
  const toggle = $("#personal-tailscale-toggle");
  if (!toggle) return;
  toggle.checked = Boolean(data.enabled && data.route_active);
  toggle.disabled = !data.manageable || (!data.enabled && (!data.installed || !data.connected || data.route_conflict));
  $("#personal-tailscale-chip").textContent = translatedText(
    data.enabled && data.route_active ? "Private link active" : data.enabled ? "Needs attention" : "Off"
  );
  $("#personal-tailscale-chip").classList.toggle("success-chip", Boolean(data.enabled && data.route_active));
  const url = $("#personal-tailscale-url");
  url.hidden = !(data.enabled && data.access_url);
  url.textContent = data.enabled && data.access_url ? `Private browser link: ${data.access_url}` : "";
  let message = "Tailscale is ready. Turn this on to share only this local library.";
  let isError = false;
  if (!data.supported) {
    message = "Automatic setup is not supported on this operating system.";
    isError = true;
  } else if (!data.installed) {
    message = "Install Tailscale on this computer, then reopen PMT.";
    isError = true;
  } else if (!data.connected) {
    message = "Open Tailscale and connect this computer first.";
    isError = true;
  } else if (data.route_conflict) {
    message = "Tailscale Serve is already assigned to another local service. PMT left it unchanged.";
    isError = true;
  } else if (data.enabled && !data.route_active) {
    message = "The private route is not active. Keep Tailscale connected and reopen PMT to retry.";
    isError = true;
  } else if (data.enabled) {
    message = "Private, account-free browser access is active while PMT stays open.";
  } else if (!data.manageable) {
    message = "Open the installed PMT application on this computer to change this setting.";
  }
  showMessage($("#personal-tailscale-state"), message, isError);
}

async function loadPersonalTailscale() {
  if (!$("#personal-tailscale-card") || state.accessMode !== "local") return;
  try {
    renderPersonalTailscale(await api("/api/device/personal-tailscale"));
  } catch (error) { showMessage($("#personal-tailscale-state"), error.message, true); }
}

async function changePersonalTailscale(event) {
  const toggle = event.currentTarget;
  toggle.disabled = true;
  try {
    if (toggle.checked) {
      const confirmed = await confirmAction(
        "Share this local library through Tailscale?",
        "Anyone permitted by your private Tailscale network who opens the link can view and edit this library without a PMT password. PMT will never enable public Tailscale Funnel.",
        "Turn on private link"
      );
      if (!confirmed) { toggle.checked = false; return; }
      const data = await api("/api/device/personal-tailscale/enable", {method: "POST", body: "{}"});
      renderPersonalTailscale(data);
      toast(data.restart_required ? "Private link prepared; reopen PMT once to keep the address stable" : "Private Tailscale link is ready");
    } else {
      const confirmed = await confirmAction(
        "Turn off the private browser link?",
        "Other devices will immediately lose browser access. This local library and every title in it remain unchanged.",
        "Turn off link"
      );
      if (!confirmed) { toggle.checked = true; return; }
      await api("/api/device/personal-tailscale/disable", {method: "POST", body: "{}"});
      await loadPersonalTailscale();
      toast("Private browser link turned off; local library unchanged");
    }
  } catch (error) {
    toggle.checked = !toggle.checked;
    showMessage($("#personal-tailscale-state"), error.message, true);
  } finally { toggle.disabled = false; }
}

async function discoverDeviceServer(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const supplied = String(new FormData(form).get("server_url") || "").trim();
  let serverUrl = supplied;
  let invitationToken = "";
  try {
    const parsed = new URL(supplied);
    invitationToken = parsed.searchParams.get("invite") || "";
    parsed.search = "";
    parsed.hash = "";
    parsed.pathname = "/";
    serverUrl = parsed.origin;
  } catch (_) { /* The backend returns the precise address validation message. */ }
  showMessage($("#remote-server-setup-state"), "Checking the server identity…");
  try {
    const server = await api("/api/device/server-connections/discover", {method: "POST", body: JSON.stringify({server_url: serverUrl})});
    state.remoteServerCandidate = server;
    const connectForm = $("#remote-server-connect-form");
    connectForm.elements.server_url.value = server.base_url;
    const toggle = $("#server-mode-toggle");
    toggle.checked = true;
    toggle.disabled = true;
    $("#access-mode-chip").textContent = translatedText("Server detected");
    $("#access-mode-chip").classList.add("success-chip");
    $("#server-runtime-state").textContent = translatedText("Server detected. Finish creating your private account to save this connection.");
    showMessage($("#remote-server-setup-state"), `${server.setup_required ? "This server still needs setup in the standalone server application." : "Verified PMT Server Beta"} · version ${server.server_version} · identity ${String(server.instance_id).slice(0, 8)}`);
    if (server.setup_required) return;
    const enrollForm = $("#remote-server-enroll-form");
    enrollForm.reset();
    enrollForm.elements.server_url.value = server.base_url;
    enrollForm.elements.invitation_token.value = invitationToken;
    showMessage($("#remote-server-enrollment-state"), invitationToken ? "Server and one-time invitation detected." : "Paste the one-time invitation code created by the standalone server.");
    openDialog($("#server-enrollment-dialog"));
  } catch (error) { showMessage($("#remote-server-setup-state"), error.message, true); }
}

function resetDeviceServerWizard() {
  state.remoteServerCandidate = null;
  $("#remote-server-discover-form").reset();
  $("#remote-server-connect-form").reset();
  $("#server-mode-toggle").checked = Boolean(state.remoteServerProfiles.find(profile => profile.enabled));
  $("#server-mode-toggle").disabled = !state.remoteServerProfiles.length;
  showMessage($("#remote-server-setup-state"), "");
}

async function enrollDeviceServer(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form));
  if (values.password !== values.confirm_password) {
    showMessage($("#remote-server-enrollment-state"), "The password confirmation does not match.", true);
    return;
  }
  delete values.confirm_password;
  values.device_label = navigator.userAgentData?.platform || navigator.platform || "Personal Media Tracker desktop";
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  showMessage($("#remote-server-enrollment-state"), "Creating the account and saving this device securely…");
  try {
    const profile = await api("/api/device/server-connections/enroll", {method: "POST", body: JSON.stringify(values)});
    await api(`/api/device/server-connections/${profile.id}/sync`, {method: "POST", body: "{}"});
    form.elements.password.value = "";
    form.elements.confirm_password.value = "";
    form.elements.invitation_token.value = "";
    $("#server-enrollment-dialog").close();
    resetDeviceServerWizard();
    await loadDeviceServerConnections();
    toast("PMT Server account created and saved on this device");
    await openDeviceServerAccount(profile.id);
  } catch (error) {
    form.elements.password.value = "";
    form.elements.confirm_password.value = "";
    showMessage($("#remote-server-enrollment-state"), error.message, true);
  } finally { button.disabled = false; }
}

async function connectDeviceServer(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form));
  values.device_label = navigator.userAgentData?.platform || navigator.platform || "Personal Media Tracker desktop";
  showMessage($("#remote-server-setup-state"), "Signing in and saving this device securely…");
  try {
    const profile = await api("/api/device/server-connections", {method: "POST", body: JSON.stringify(values)});
    await api(`/api/device/server-connections/${profile.id}/sync`, {method: "POST", body: "{}"});
    form.elements.password.value = "";
    resetDeviceServerWizard();
    await loadDeviceServerConnections();
    toast("PMT Server connected");
    await openDeviceServerAccount(profile.id);
  } catch (error) {
    form.elements.password.value = "";
    showMessage($("#remote-server-setup-state"), error.message, true);
  }
}

async function manageDeviceServer(event) {
  const button = event.target.closest("[data-remote-action]");
  if (!button) return;
  const profileId = button.dataset.profileId;
  button.disabled = true;
  try {
    const action = button.dataset.remoteAction;
    if (action === "review") {
      await reviewDeviceServerConflicts(profileId);
    } else if (action === "open") {
      await openDeviceServerAccount(profileId);
    } else if (action === "sync") {
      const result = await api(`/api/device/server-connections/${profileId}/sync`, {method: "POST", body: "{}"});
      toast(result.conflicts ? `${result.conflicts} queued edit${result.conflicts === 1 ? " needs" : "s need"} review` : "Server synchronization complete");
      if (result.conflicts) await reviewDeviceServerConflicts(profileId);
    } else if (action === "pause") {
      if (!await confirmAction("Disconnect this application from PMT Server?", "This device returns to its separate local library. Nothing is deleted from PMT Server, and the saved device session is retained for reconnection.", "Disconnect this app")) return;
      await api(`/api/device/server-connections/${profileId}`, {method: "PATCH", body: JSON.stringify({enabled: false})});
      toast("Disconnected on this device; the server account remains intact");
    } else if (action === "resume") {
      await api(`/api/device/server-connections/${profileId}`, {method: "PATCH", body: JSON.stringify({enabled: true})});
      await api(`/api/device/server-connections/${profileId}/sync`, {method: "POST", body: "{}"});
      toast("Reconnected with the saved device session");
      await openDeviceServerAccount(profileId);
    } else if (action === "forget") {
      if (!await confirmAction("Forget this server on this device?", "The saved device session, local server cache, and any queued edits on this device are removed. The account and all server data remain on PMT Server.", "Forget on this device")) return;
      await api(`/api/device/server-connections/${profileId}`, {method: "DELETE"});
      toast("Saved server removed from this device");
    }
    await loadDeviceServerConnections();
  } catch (error) { showMessage($("#remote-server-setup-state"), error.message, true); }
  finally { button.disabled = false; }
}

async function manageDeviceServerConflict(event) {
  const close = event.target.closest("[data-close-remote-conflicts]");
  if (close) {
    $("#remote-server-conflicts").hidden = true;
    return;
  }
  const button = event.target.closest("[data-remote-conflict-action]");
  if (!button) return;
  button.disabled = true;
  const profileId = button.dataset.profileId;
  try {
    await api(`/api/device/server-connections/${profileId}/conflicts/${button.dataset.requestId}`, {method: "POST", body: JSON.stringify({action: button.dataset.remoteConflictAction})});
    if (button.dataset.remoteConflictAction === "rebase") await api(`/api/device/server-connections/${profileId}/sync`, {method: "POST", body: "{}"});
    await loadDeviceServerConnections();
    await reviewDeviceServerConflicts(profileId);
    toast(button.dataset.remoteConflictAction === "discard" ? "Server version kept" : "Your queued edit was retried");
  } catch (error) { showMessage($("#remote-server-setup-state"), error.message, true); }
  finally { button.disabled = false; }
}

async function loadServerAccounts() {
  const [users, me] = await Promise.all([api("/api/v1/admin/users"), api("/api/v1/me")]);
  $("#server-user-list").innerHTML = (users.items || []).map(user => `
    <article class="integration-card server-account-row"><div><strong>${esc(user.display_name)}</strong><p class="muted">@${esc(user.username)} · ${esc(translatedText(user.role === "admin" ? "Server account" : "Regular user"))} · ${esc(translatedText(user.state === "active" ? "Can sign in" : "Sign-in disabled"))}</p></div><div class="metadata-actions">${user.id !== me.id ? `<button type="button" class="quiet" data-server-user-action="recovery" data-user-id="${esc(user.id)}" data-user-name="${esc(user.display_name)}">${esc(translatedText("Create recovery link"))}</button><button type="button" class="${user.state === "active" ? "quiet-danger" : "quiet"}" data-server-user-action="toggle" data-user-id="${esc(user.id)}" data-user-name="${esc(user.display_name)}" data-user-state="${esc(user.state)}">${esc(translatedText(user.state === "active" ? "Disable sign-in" : "Enable sign-in"))}</button>` : `<span class="status-badge">${esc(translatedText("Server account"))}</span>`}</div></article>`).join("");
}

async function createServerInvitation(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = new FormData(form);
  const payload = {role: values.get("role"), expires_hours: Number(values.get("expires_hours"))};
  if (values.get("email")) payload.email = values.get("email");
  try {
    const data = await api("/api/v1/admin/invitations", {method: "POST", body: JSON.stringify(payload)});
    const output = $("#server-invitation-output");
    output.hidden = false;
    output.textContent = data.redeem_url || data.token;
    form.reset();
    toast("Invitation created; copy it now");
  } catch (error) { showMessage($("#settings-message"), error.message, true); }
}

async function manageServerUser(event) {
  const button = event.target.closest("[data-server-user-action]");
  if (!button) return;
  try {
    if (button.dataset.serverUserAction === "recovery") {
      if (!await confirmAction(`Create a recovery link for ${button.dataset.userName}?`, "The one-time link lets this member replace their password. It expires after 24 hours and will be shown only once.", "Create recovery link")) return;
      const data = await api(`/api/v1/admin/users/${button.dataset.userId}/recovery-invitation`, {method: "POST", body: "{}"});
      const output = $("#server-invitation-output");
      output.hidden = false;
      output.textContent = data.redeem_url || data.token;
      toast("Recovery token created; copy it now");
    } else {
      const nextState = button.dataset.userState === "active" ? "disabled" : "active";
      if (nextState === "disabled") {
        if (!await confirmAction(`Disable sign-in for ${button.dataset.userName}?`, "This immediately signs the member out on every device. Their private library, lists, ratings, and notes stay stored on this server.", "Review disabling")) return;
        if (!await confirmAction("Confirm account lockout", `${button.dataset.userName} will be unable to sign in until the server owner enables the account again. No data will be deleted.`, "Disable sign-in")) return;
      } else if (!await confirmAction(`Enable sign-in for ${button.dataset.userName}?`, "This restores access to the member's existing account and stored data. It does not create a new account or password.", "Enable sign-in")) return;
      await api(`/api/v1/admin/users/${button.dataset.userId}`, {method: "PATCH", body: JSON.stringify({state: nextState})});
      await loadServerAccounts();
      toast(`Account ${nextState}`);
    }
  } catch (error) { showMessage($("#settings-message"), error.message, true); }
}

async function activateServer(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = new FormData(form);
  showMessage($("#server-activation-message"), "Creating a safety backup and checking configuration…");
  try {
    const data = await api("/api/server/activate", {
      method: "POST",
      body: JSON.stringify({
        public_base_url: values.get("public_base_url"),
        owner_password: values.get("owner_password"),
        bind_host: "127.0.0.1",
        port: Number(values.get("port")),
        trusted_proxy_ips: String(values.get("trusted_proxy_ips") || "").split(",").map(value => value.trim()).filter(Boolean)
      })
    });
    form.reset();
    showMessage($("#server-activation-message"), `Prepared safely with backup ${data.backup}. Restart the app, then open ${data.access_url}.`);
  } catch (error) { showMessage($("#server-activation-message"), error.message, true); }
}

async function ownerLogin(event) {
  event.preventDefault();
  // Safari clears Event.currentTarget once the synchronous callback returns.
  // Keep stable references before awaiting so a rejected login can always
  // restore the form instead of remaining stuck on "Signing in…".
  const form = event.currentTarget;
  const submit = form.querySelector("button[type='submit']");
  const passwordInput = form.querySelector("[name='password']");
  const values = new FormData(form);
  const username = values.get("username");
  const password = values.get("password");
  showMessage($("#login-message"), "Signing in…");
  if (submit) submit.disabled = true;
  try {
    await api("/api/auth/login", {method: "POST", body: JSON.stringify({username, password})});
    const parameters = new URLSearchParams(window.location.search);
    parameters.set("view", "library");
    window.location.replace(`${window.location.pathname}?${parameters.toString()}`);
  } catch (error) {
    if (passwordInput) passwordInput.value = "";
    showMessage($("#login-message"), error.message, true);
  } finally {
    if (submit) submit.disabled = false;
  }
}

async function recoverLocalServerAccount(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const authenticatedRecovery = form.id === "authenticated-host-recovery-form";
  const messageElement = authenticatedRecovery ? $("#authenticated-host-recovery-message") : $("#login-message");
  const submit = form.querySelector("button[type='submit']");
  const values = new FormData(form);
  const newPassword = String(values.get("new_password") || "");
  const confirmation = String(values.get("confirm_password") || "");
  if (newPassword !== confirmation) {
    showMessage(messageElement, "The new passwords do not match.", true);
    return;
  }
  showMessage(messageElement, "Resetting the server-account password…");
  if (submit) submit.disabled = true;
  try {
    await api("/api/v1/setup/local-host-recovery", {
      method: "POST",
      body: JSON.stringify({new_password: newPassword})
    });
    form.reset();
    const parameters = new URLSearchParams(window.location.search);
    parameters.set("view", "library");
    window.location.replace(`${window.location.pathname}?${parameters.toString()}`);
  } catch (error) {
    showMessage(messageElement, error.message, true);
  } finally {
    if (submit) submit.disabled = false;
  }
}

async function completeServerBootstrap(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = new FormData(form);
  showMessage($("#login-message"), "Completing secure server setup…");
  try {
    await api("/api/v1/setup/bootstrap", {method: "POST", body: JSON.stringify(Object.fromEntries(values))});
    form.reset();
    showMessage($("#login-message"), "Server setup complete. Sign in to continue.");
    showAuthentication("login");
  } catch (error) { showMessage($("#login-message"), error.message, true); }
}

async function redeemServerInvitation(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = new FormData(form);
  showMessage($("#login-message"), "Creating your private account…");
  try {
    await api("/api/v1/auth/invitations/redeem", {method: "POST", body: JSON.stringify(Object.fromEntries(values))});
    history.replaceState({}, "", window.location.pathname);
    const username = values.get("username") || "";
    form.reset();
    $("#login-form [name='username']").value = username;
    showMessage($("#login-message"), "Account created. Sign in to continue.");
    showAuthentication("login");
  } catch (error) { showMessage($("#login-message"), error.message, true); }
}

async function ownerSecurityAction(path, body, success, messageElement = $("#settings-message")) {
  try {
    await api(path, {method: "POST", body: JSON.stringify(body || {})});
    toast(success);
    if (path.includes("password") || path.includes("revoke") || path.includes("logout")) {
      state.currentUser = null;
      applySignedOutAppearance();
      window.location.replace(`${window.location.pathname}?view=library`);
    }
    return true;
  } catch (error) {
    showMessage(messageElement, error.message, true);
    return false;
  }
}

async function createCalendarFeed() {
  try {
    const data = await api("/api/exports/upcoming-releases/feed", {method: "POST", body: "{}"});
    const output = $("#calendar-feed-url");
    output.hidden = false;
    output.textContent = data.feed_url;
    try { await navigator.clipboard.writeText(data.feed_url); toast("Calendar feed URL copied — it is shown only now"); }
    catch (_) { toast("Calendar feed URL created — copy and store it now"); }
  } catch (error) { showMessage($("#settings-message"), error.message, true); }
}

async function revokeCalendarFeeds() {
  try {
    const data = await api("/api/exports/upcoming-releases/feed", {method: "DELETE"});
    $("#calendar-feed-url").hidden = true;
    toast(`${data.revoked} calendar feed URL${data.revoked === 1 ? "" : "s"} revoked`);
  } catch (error) { showMessage($("#settings-message"), error.message, true); }
}

function shortcutSignature(event, {capturing = false} = {}) {
  if (["ShiftLeft", "ShiftRight", "ControlLeft", "ControlRight", "AltLeft", "AltRight", "MetaLeft", "MetaRight"].includes(event.code)) return null;
  if (["Tab", "Escape", "Enter"].includes(event.code)) return null;
  const hasPrimaryModifier = event.metaKey || event.ctrlKey || event.altKey;
  if (capturing && !hasPrimaryModifier && !/^F(?:[1-9]|1[0-2])$/.test(event.code)) return null;
  return [event.metaKey && "Meta", event.ctrlKey && "Control", event.altKey && "Alt", event.shiftKey && "Shift", event.code].filter(Boolean).join("+");
}

function shortcutDisplay(signature) {
  if (!signature) return "Not set";
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || "");
  return signature.split("+").map(part => {
    if (part === "Meta") return isMac ? "⌘" : "Meta";
    if (part === "Control") return "Ctrl";
    if (part === "Alt") return isMac ? "Option" : "Alt";
    if (part === "Shift") return "Shift";
    if (part.startsWith("Key")) return part.slice(3);
    if (part.startsWith("Digit")) return part.slice(5);
    return ({Space: "Space", Slash: "/", Comma: ",", Period: ".", Minus: "-", Equal: "="})[part] || part;
  }).join(" ");
}

function renderKeyboardShortcuts(shortcuts = {}) {
  state.keyboardShortcuts = {...shortcuts};
  $$("[data-shortcut-row]").forEach(row => {
    const action = row.dataset.shortcutRow;
    const value = state.keyboardShortcuts[action] || "";
    $("[data-shortcut-value]", row).textContent = shortcutDisplay(value);
    $("[data-clear-shortcut]", row).hidden = !value;
    const record = $("[data-record-shortcut]", row);
    record.dataset.capturing = "false";
    record.textContent = "Set shortcut";
  });
}

async function saveKeyboardShortcuts() {
  await api("/api/settings/general", {method: "PUT", body: JSON.stringify({keyboard_shortcuts: state.keyboardShortcuts})});
  renderKeyboardShortcuts(state.keyboardShortcuts);
}

function beginShortcutCapture(action) {
  state.capturingShortcut = action;
  renderKeyboardShortcuts(state.keyboardShortcuts);
  const button = $(`[data-record-shortcut="${action}"]`);
  button.dataset.capturing = "true";
  button.textContent = "Press keys…";
  showMessage($("#shortcut-capture-status"), "Press your preferred combination. Use Command, Control, or Option with another key; press Escape to cancel.");
}

async function captureShortcut(event) {
  const action = state.capturingShortcut;
  if (!action) return false;
  event.preventDefault();
  event.stopImmediatePropagation();
  if (event.code === "Escape") {
    state.capturingShortcut = null;
    renderKeyboardShortcuts(state.keyboardShortcuts);
    showMessage($("#shortcut-capture-status"), "Shortcut assignment cancelled.");
    return true;
  }
  const signature = shortcutSignature(event, {capturing: true});
  if (!signature) {
    showMessage($("#shortcut-capture-status"), "Use Command, Control, or Option with another key. F1–F12 may be used alone.", true);
    return true;
  }
  const duplicate = Object.entries(state.keyboardShortcuts).find(([otherAction, value]) => otherAction !== action && value === signature);
  if (duplicate) {
    showMessage($("#shortcut-capture-status"), `That combination is already assigned to ${duplicate[0].replaceAll("_", " ")}.`, true);
    return true;
  }
  state.keyboardShortcuts[action] = signature;
  state.capturingShortcut = null;
  try {
    await saveKeyboardShortcuts();
    showMessage($("#shortcut-capture-status"), `${shortcutDisplay(signature)} saved.`);
  } catch (error) {
    delete state.keyboardShortcuts[action];
    renderKeyboardShortcuts(state.keyboardShortcuts);
    showMessage($("#shortcut-capture-status"), error.message, true);
  }
  return true;
}

async function clearShortcut(action) {
  delete state.keyboardShortcuts[action];
  try {
    await saveKeyboardShortcuts();
    showMessage($("#shortcut-capture-status"), "Shortcut cleared.");
  } catch (error) { showMessage($("#shortcut-capture-status"), error.message, true); }
}

function runConfiguredShortcut(action) {
  if (action === "quick_add") return focusQuickAdd();
  if (action === "settings") return openSettings();
  if (["library", "currently_watching", "active_shows", "rankings", "insights"].includes(action)) {
    switchView(action, {push: true, scrollTop: true});
  }
}

async function openSettings() {
  const dialog = $("#settings-dialog");
  $("#tmdb-token").value = "";
  $("#theme-preference").value = themePreference();
  applyAccent(accentPreference(), customAccentPreference());
  applyBackgroundColor(backgroundPreference(), backgroundStrengthPreference(), backgroundModePreference());
  applyMediaArtworkPreference(mediaArtworkPreference());
  applySidebarPreferences(state.sidebarMode, state.navigationOrder, {persist: false});
  $("#settings-intro").hidden = state.settingsPrivacyReminderDismissed;
  showMessage($("#settings-message"), "");
  openDialog(dialog);
  dialog.scrollTop = 0;
  const visiblePanel = dialog.querySelector('[data-settings-panel]:not([hidden])');
  if (visiblePanel) visiblePanel.scrollTop = 0;
  try {
    await state.appearanceSave;
    const [metadata, general] = await Promise.all([
      api("/api/settings/metadata"),
      api("/api/settings/general")
    ]);
    renderMetadataSettings(metadata);
    renderGeneralSettings(general);
    if (state.accessMode === "local" || state.currentUser?.role === "admin") await loadServerReadiness();
    if (state.accessMode === "local") await loadPersonalTailscale();
    await updateMetadataReviewCount();
    await updateRatingReviewCount();
    await pollEnrichment();
  } catch (error) { showMessage($("#settings-message"), error.message, true); }
}

function renderMetadataSettings(data) {
  const serverAccount = state.accessMode === "server" && state.currentUser?.role === "admin";
  const regularUser = state.accessMode === "server" && state.currentUser?.role === "member";
  const activeLabel = data.credential_scope === "server_shared" && data.tmdb_configured ? "Using server token" : data.tmdb_configured ? "Configured" : "Not configured";
  setLocalizedText($("#tmdb-status"), activeLabel);
  setLocalizedText($("#tmdb-provider-marker"), activeLabel);
  if (serverAccount) {
    $("#tmdb-scope-title").textContent = translatedText("Optional shared server token");
    $("#tmdb-scope-copy").textContent = translatedText("Regular users keep individual tokens by default. They can explicitly use this credential only when their own token is unavailable; shared use consumes one server-wide quota.");
  } else if (regularUser) {
    $("#tmdb-scope-title").textContent = translatedText("Your individual token is recommended");
    $("#tmdb-scope-copy").textContent = translatedText(data.individual_token_configured ? "Your private token is active for this regular user account." : "Add your own token to keep requests and quota separate from other users on this server.");
  } else {
    $("#tmdb-scope-title").textContent = translatedText("Optional metadata token");
    $("#tmdb-scope-copy").textContent = translatedText("This credential stays with the local installation and is never included in exports or backups.");
  }
  $("#server-token-fallback-setting").hidden = !regularUser;
  $("#use-server-tmdb-token").checked = Boolean(data.use_server_token);
  $("#use-server-tmdb-token").disabled = !data.server_token_available;
  $("#settings-form details").hidden = regularUser;
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
  $("#keychain-storage").disabled = !data.keychain_available || regularUser;
  $("#copy-keychain-token").hidden = !data.keychain_available || regularUser;
  $("#copy-keychain-token").textContent = "Copy existing system-vault token locally";
  $("#copy-keychain-token").title = "This explicit action checks for a token saved by an earlier version. Your operating system may ask for authentication once.";
  $("#migrate-legacy-token").hidden = regularUser || !data.legacy_token_available || data.storage === "environment" || data.storage === "keychain" || data.storage === "local_secret_file";
  $("#clear-tmdb").disabled = regularUser ? !data.individual_token_configured : !data.tmdb_configured;
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
  applyBackgroundImage(data);
  applyMediaArtworkPreference(Boolean(data.media_artwork_tint));
  applyMediaArtworkFullColorPreference(Boolean(data.media_artwork_full_color));
  applyEpisodeProgressPreference(data.show_episode_progress !== false);
  applyIconPreference(data.icon_background_color || DEFAULT_ICON_BACKGROUND, data.icon_text_color || DEFAULT_ICON_TEXT, Boolean(data.icon_follow_accent));
  state.advancedRatingsEnabled = Boolean(data.advanced_ratings_enabled);
  state.releaseCheckMode = data.release_check_mode || null;
  state.settingsPrivacyReminderDismissed = Boolean(data.settings_privacy_reminder_dismissed);
  $("#settings-intro").hidden = state.settingsPrivacyReminderDismissed;
  applySidebarPreferences(data.sidebar_mode || "expanded", data.navigation_order || "standard");
  if ($("#release-check-mode")) $("#release-check-mode").checked = state.releaseCheckMode === "automatic";
  renderKeyboardShortcuts(data.keyboard_shortcuts || {});
  $("#advanced-ratings-enabled").checked = state.advancedRatingsEnabled;
  setLocalizedText(
    $("#advanced-ratings-state"),
    state.advancedRatingsEnabled ? "Enabled · assessments and comparisons stay optional." : "Off · direct 1–10 ratings remain available everywhere.",
    state.advancedRatingsEnabled ? "Activé · les évaluations guidées et les comparaisons restent facultatives." : "Désactivé · les notes directes de 1 à 10 restent disponibles partout."
  );
  $("#general-timezone").value = data.timezone || "";
  setSelectValue($("#general-language"), data.language || "en-US");
  setSelectValue($("#general-region"), data.region || "US");
  $("#interface-language").value = supportedInterfaceLanguages.has(data.interface_language) ? data.interface_language : "en";
  state.generalSettingsSnapshot = {
    timezone: $("#general-timezone").value,
    language: $("#general-language").value,
    region: $("#general-region").value,
    interfaceLanguage: $("#interface-language").value,
    sidebarMode: state.sidebarMode,
    navigationOrder: state.navigationOrder,
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

async function setAdvancedRatingsEnabled(enabled) {
  const input = $("#advanced-ratings-enabled");
  input.disabled = true;
  showMessage($("#settings-message"), enabled ? "Enabling advanced rating tools…" : "Hiding advanced rating tools…");
  try {
    await state.appearanceSave;
    await api("/api/settings/general", {method: "PUT", body: JSON.stringify({advanced_ratings_enabled: enabled})});
    const data = await api("/api/settings/general");
    state.rankingMode = enabled ? "technical" : "personal";
    state.rankingsLoaded = false;
    state.ratingRubric = null;
    renderGeneralSettings(data);
    showMessage($("#settings-message"), enabled ? "Advanced rating tools enabled. Direct ratings still work exactly as before." : "Advanced tools hidden. Existing assessments and comparisons were retained.");
  } catch (error) {
    input.checked = !enabled;
    showMessage($("#settings-message"), error.message, true);
  } finally { input.disabled = false; }
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
    interface_language: $("#interface-language").value,
    sidebar_mode: $("#sidebar-mode").value,
    navigation_order: $("#navigation-order").value
  };
}

function generalSettingsDirty() {
  if (!state.generalSettingsSnapshot) return false;
  const current = generalSettingsPayload();
  return current.timezone !== (state.generalSettingsSnapshot.timezone || null) || current.language !== state.generalSettingsSnapshot.language || current.region !== state.generalSettingsSnapshot.region || current.interface_language !== state.generalSettingsSnapshot.interfaceLanguage || current.sidebar_mode !== state.generalSettingsSnapshot.sidebarMode || current.navigation_order !== state.generalSettingsSnapshot.navigationOrder;
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
  applySidebarPreferences(state.generalSettingsSnapshot.sidebarMode, state.generalSettingsSnapshot.navigationOrder);
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
    const serverAccount = state.accessMode === "server" && state.currentUser?.role === "admin";
    const regularUser = state.accessMode === "server" && state.currentUser?.role === "member";
    showMessage($("#settings-message"), regularUser ? "Your individual TMDb token was saved and activated for this account." : serverAccount ? "The optional shared server token was saved. Regular users must still opt in before relying on it." : credentialStorage === "keychain" ? "TMDb token saved to the operating-system credential vault and activated." : "TMDb token saved in the local configuration file and activated. No operating-system password prompt is required.");
    toast("Metadata settings saved");
    if (data.tmdb_configured) await startEnrichment();
  } catch (error) { showMessage($("#settings-message"), error.message, true); }
}

async function saveServerTokenPreference(enabled) {
  try {
    const data = await api("/api/settings/metadata", {method: "PUT", body: JSON.stringify({use_server_token: enabled})});
    renderMetadataSettings(data);
    showMessage($("#settings-message"), enabled ? "Server-token fallback enabled. Your individual token remains preferred whenever it is configured." : "Server-token fallback disabled. Keyless providers and your individual token remain available.");
  } catch (error) {
    $("#use-server-tmdb-token").checked = !enabled;
    showMessage($("#settings-message"), error.message, true);
  }
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
  const regularUser = state.accessMode === "server" && state.currentUser?.role === "member";
  const serverAccount = state.accessMode === "server" && state.currentUser?.role === "admin";
  const explanation = regularUser ? "This removes only your individual token. Keyless providers remain available, and an enabled shared-server fallback can still be used." : serverAccount ? "This removes the shared server token. Regular users' individual tokens are not changed, but users relying on the shared fallback will lose TMDb access." : "Movie and TV search will be unavailable until another token is saved. If local storage is active, an older inactive system-vault item is left untouched so the app does not unexpectedly request authentication.";
  if (!await confirmAction("Clear the active TMDb token?", explanation, "Clear token")) return;
  try {
    const data = await api("/api/settings/metadata", {method: "PUT", body: JSON.stringify({clear_tmdb_token: true})});
    $("#tmdb-token").value = "";
    renderMetadataSettings(data);
    showMessage($("#settings-message"), regularUser ? "Your individual token was cleared." : serverAccount ? "The shared server token was cleared; individual user tokens were not changed." : data.tmdb_configured ? "The saved token was cleared; an environment or legacy override remains active." : "TMDb token cleared.");
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
    const interfaceChanged = payload.interface_language !== state.generalSettingsSnapshot?.interfaceLanguage;
    await state.appearanceSave;
    await api("/api/settings/general", {method: "PUT", body: JSON.stringify(payload)});
    if (interfaceChanged) {
      try { localStorage.setItem("watchtracker-interface-language", payload.interface_language); } catch (_) { /* optional */ }
      window.location.reload();
      return;
    }
    renderGeneralSettings(await api("/api/settings/general"));
    updateGeneralSettingsState(true);
    showMessage(
      $("#settings-message"),
      translatedText("General settings saved and verified.")
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
  $("#update-available-actions").hidden = true;
  $("#update-progress-region").hidden = true;
  showMessage($("#update-status"), "Checking GitHub Releases…");
  try {
    const data = await api("/api/updates/check", {method: "POST", body: "{}"});
    if (data.update_available) {
      $("#open-update-release").href = data.release_url;
      $("#download-update").hidden = !data.download_supported;
      $("#update-available-actions").hidden = false;
      showMessage($("#update-status"), data.download_supported ? `Version ${data.latest_version} is available.` : `Version ${data.latest_version} is available. ${data.download_unavailable_reason || "Use Open the Release to install it."}`);
    } else showMessage($("#update-status"), `You’re up to date (version ${data.current_version}).`);
  } catch (error) { showMessage($("#update-status"), error.message, true); }
  finally { button.disabled = false; }
}

async function downloadUpdateInApp() {
  const button = $("#download-update");
  button.disabled = true;
  $("#update-progress-region").hidden = false;
  $("#update-progress").removeAttribute("value");
  showMessage($("#update-progress-status"), "Preparing the verified update download…");
  try {
    await api("/api/updates/download", {method: "POST", body: "{}"});
    while (true) {
      const status = await api("/api/updates/status");
      const progress = $("#update-progress");
      if (status.total_bytes || status.percent) progress.value = Number(status.percent || 0);
      else progress.removeAttribute("value");
      showMessage($("#update-progress-status"), status.message || "Preparing update…", status.state === "failed");
      if (status.state === "failed") throw new Error(status.message || "The update could not be prepared safely.");
      if (status.ready_to_install) {
        const installed = await window.pywebview?.api?.install_update?.();
        if (!installed) throw new Error("The verified update is ready, but PMT could not start the installer. Use Open the Release instead.");
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 450));
    }
  } catch (error) {
    showMessage($("#update-progress-status"), error.message, true);
    button.disabled = false;
  }
}

function integrationStateLabel(value) {
  return translatedText(({connected: "Connected", syncing: "Syncing", needs_attention: "Needs attention", paused: "Paused", not_configured: "Not configured"})[value] || "Not configured");
}

function integrationProviderHtml(provider) {
  const status = provider.available ? translatedText("Available") : translatedText("Unavailable");
  const configured = state.integrationConnections.some(connection => connection.provider_slug === provider.slug);
  return `<button type="button" class="connection-provider-button" data-connection-provider="${esc(provider.slug)}" aria-pressed="false"><span translate="no">${esc(provider.name)}</span><small>${esc(configured ? translatedText("Configured") : status)}</small></button>`;
}

function selectConnectionProvider(name) {
  state.selectedConnectionProvider = name;
  $$('[data-connection-provider]').forEach(button => {
    const selected = button.dataset.connectionProvider === name;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  const staticProvider = ["tmdb", "jikan", "kitsu", "tvmaze", "wikidata"].includes(name);
  $$('[data-connection-panel]').forEach(panel => { panel.hidden = panel.dataset.connectionPanel !== (staticProvider ? name : "integration"); });
  if (staticProvider) return;
  const provider = state.integrationProviders.find(item => item.slug === name);
  if (!provider) return;
  const requirements = [...(provider.requirements || []), ...(provider.limitations || [])];
  const configured = state.integrationConnections.filter(connection => connection.provider_slug === name);
  $("#integration-provider-detail").innerHTML = `<div class="provider-setting"><div><strong translate="no">${esc(provider.name)}</strong><p>${esc(translatedText(provider.summary))}</p></div><span class="chip ${provider.available ? "success-chip" : ""}">${esc(translatedText(provider.available ? "Available" : "Unavailable"))}</span></div><p>${esc(translatedText(provider.available ? "Setup begins with a protected connection test and a dry-run preview. Outbound changes remain off until explicitly enabled." : (provider.availability_reason || "This provider adapter is planned for a later release.")))}</p>${requirements.length ? `<details class="compact-disclosure"><summary>${esc(translatedText("Requirements & limitations"))}</summary><ul class="integration-requirements">${requirements.map(value => `<li>${esc(translatedText(value))}</li>`).join("")}</ul></details>` : ""}`;
  $("#integration-connections").innerHTML = configured.length ? configured.map(integrationConnectionHtml).join("") : `<p class="muted">${esc(translatedText("Not configured. Setup controls appear when this adapter is available and fully tested."))}</p>`;
}

function integrationConnectionHtml(connection) {
  const stateLabel = integrationStateLabel(connection.state);
  const lastSuccess = connection.last_success_at ? new Date(connection.last_success_at).toLocaleString(interfaceLocale()) : translatedText("Never");
  const paused = connection.state === "paused";
  return `<article class="integration-connection-card" data-connection="${esc(connection.id)}"><div class="integration-card-head"><div><h4 translate="no">${esc(connection.label)}</h4><p translate="no">${esc(connection.provider_slug)}</p></div><span class="integration-status-pill ${esc(connection.state)}">${esc(stateLabel)}</span></div><p class="muted">${esc(translatedText("Last successful run"))}: ${esc(lastSuccess)}</p>${connection.paused_reason ? `<p class="warning-text">${esc(translatedText(connection.paused_reason))}</p>` : ""}<div class="integration-card-actions"><button type="button" class="quiet" data-integration-action="test">${esc(translatedText("Test"))}</button><button type="button" class="quiet" data-integration-action="preview">${esc(translatedText("Preview pull"))}</button><button type="button" class="quiet" data-integration-action="toggle">${esc(translatedText(paused || !connection.enabled ? "Resume" : "Pause"))}</button><button type="button" class="quiet-danger" data-integration-action="disconnect">${esc(translatedText("Disconnect"))}</button></div></article>`;
}

async function loadIntegrations() {
  showMessage($("#integration-status"), "Loading integration status…");
  try {
    const [providers, connections] = await Promise.all([
      api("/api/integrations/catalog"),
      api("/api/integrations/connections")
    ]);
    state.integrationsLoaded = true;
    state.integrationConnections = connections.connections || [];
    state.integrationProviders = (providers.providers || []).filter(provider => !["tmdb", "anilist", "jikan"].includes(provider.slug));
    $("#integration-provider-catalog").innerHTML = state.integrationProviders.map(integrationProviderHtml).join("") || `<p class="muted">${esc(translatedText("No integration providers are registered."))}</p>`;
    $("#integration-reachability").hidden = connections.access_mode !== "local";
    showMessage($("#integration-status"), "Provider-specific adapters remain unavailable until their end-to-end privacy and replay tests pass.");
    $$('[data-connection-provider]').forEach(button => {
      if (button.dataset.connectionProviderBound) return;
      button.dataset.connectionProviderBound = "true";
      button.addEventListener("click", () => selectConnectionProvider(button.dataset.connectionProvider));
    });
    selectConnectionProvider(state.selectedConnectionProvider);
  } catch (error) {
    showMessage($("#integration-status"), error.message, true);
  }
}

async function handleIntegrationAction(button) {
  const card = button.closest("[data-connection]");
  const connection = state.integrationConnections.find(item => item.id === card?.dataset.connection);
  if (!connection) return;
  const action = button.dataset.integrationAction;
  button.disabled = true;
  try {
    if (action === "disconnect") {
      if (!await confirmAction("Disconnect this integration?", "Protected credentials and its connection history will be removed. Your PMT library remains unchanged.", "Disconnect")) return;
      await api(`/api/integrations/connections/${connection.id}`, {method: "DELETE"});
    } else if (action === "toggle") {
      await api(`/api/integrations/connections/${connection.id}`, {method: "PATCH", body: JSON.stringify({enabled: !connection.enabled || connection.state === "paused"})});
    } else {
      const capability = action === "test" ? "test_connection" : Object.keys(connection.capabilities || {}).find(value => value.startsWith("pull_"));
      if (!capability) throw new Error("This connection has no enabled pull capability.");
      const result = await api(`/api/integrations/connections/${connection.id}/runs`, {method: "POST", body: JSON.stringify({capability, direction: action === "test" ? "test" : "pull", dry_run: action === "preview"})});
      toast(result.message || "Integration run completed");
    }
    await loadIntegrations();
  } catch (error) { showMessage($("#integration-status"), error.message, true); }
  finally { button.disabled = false; }
}

function selectSettingsTab(name) {
  if (name === "integrations") name = "metadata";
  $$('[data-settings-tab]').forEach(button => {
    const selected = button.dataset.settingsTab === name;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  let selectedPanel = null;
  $$('[data-settings-panel]').forEach(panel => {
    panel.hidden = panel.dataset.settingsPanel !== name;
    if (!panel.hidden) selectedPanel = panel;
  });
  if (selectedPanel) selectedPanel.scrollTo({top: 0, behavior: "auto"});
  $("#settings-dialog").scrollTo({top: 0, behavior: "auto"});
}

function showOnboardingStep(name) {
  $$('[data-onboarding-step]').forEach(panel => { panel.hidden = panel.dataset.onboardingStep !== name; });
}

async function completeOnboarding(action) {
  try { localStorage.setItem("watchtracker-onboarding-complete", "true"); } catch (_) { /* optional */ }
  $("#onboarding-dialog").close();
  if (action === "search") focusQuickAdd();
  if (action === "import") openDialog($("#import-dialog"));
  if (action === "manual") openDialog($("#manual-dialog"));
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
    openDialog($("#onboarding-dialog"));
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
  state.layout = "grid";
  try { localStorage.removeItem("watchtracker-layout"); } catch (_) { /* optional */ }
  $("#library").className = "library grid";
  if (persist) persistNavigationState();
}

document.addEventListener("DOMContentLoaded", () => {
  if ((state.nativeHostToken || state.nativeSessionHandoff) && window.location.hash) {
    history.replaceState({}, "", `${window.location.pathname}${window.location.search}`);
  }
  restoreNavigationState();
  applyInterfaceLanguage(interfaceLanguagePreference());
  const localizationObserver = new MutationObserver(records => {
    if (state.interfaceLanguage === "en") return;
    records.forEach(record => record.addedNodes.forEach(node => localizeTree(node)));
  });
  localizationObserver.observe(document.body, {childList: true, subtree: true});
  applyTheme(themePreference());
  applyAccent(accentPreference(), customAccentPreference());
  applyBackgroundColor(backgroundPreference(), backgroundStrengthPreference(), backgroundModePreference());
  applyIconPreference();
  window.addEventListener("pywebviewready", () => {
    syncNativeWindowBackground();
    applyIconPreference();
  }, {once: true});
  applyMediaArtworkPreference(mediaArtworkPreference());
  applyMediaArtworkFullColorPreference(mediaArtworkFullColorPreference());
  applyEpisodeProgressPreference(episodeProgressPreference());
  if (state.nativeWindow) {
    $$("dialog").forEach(dialog => dialog.addEventListener("close", syncNativeDialogLayer));
    document.addEventListener("keydown", event => {
      if (event.key !== "Escape") return;
      const dialog = $("dialog.native-dialog-active[open]");
      if (!dialog) return;
      const cancelEvent = new Event("cancel", {cancelable: true});
      if (dialog.dispatchEvent(cancelEvent)) dialog.close("cancel");
    });
  }
  bindHelpTips();
  try {
    $("#timezone-options").innerHTML = Intl.supportedValuesOf("timeZone").map(zone => `<option value="${esc(zone)}"></option>`).join("");
  } catch (_) { $("#timezone-options").innerHTML = '<option value="UTC"></option><option value="America/Los_Angeles"></option><option value="America/New_York"></option><option value="Europe/London"></option><option value="Europe/Paris"></option><option value="Asia/Shanghai"></option><option value="Asia/Tokyo"></option>'; }
  setLayout(state.layout, {persist: false});
  applyNavigationControls();
  switchView(state.view, {persist: false});
  $$(".nav-button, #server-console-nav").forEach(button => button.addEventListener("click", () => switchView(button.dataset.view, {push: true, scrollTop: true})));
  $("#toggle-sidebar").addEventListener("click", toggleSidebar);
  $(".brand").addEventListener("click", async event => {
    event.preventDefault();
    if (state.currentUser?.role === "admin" && !state.currentUser?.legacy_personal_library && state.serverConsoleAvailable) {
      switchView("server_console", {push: state.view !== "server_console", scrollTop: true});
      return;
    }
    switchView("library", {push: state.view !== "library", scrollTop: true});
    await loadLibrary({showSkeleton: false});
    scrollDocumentTop();
    requestAnimationFrame(() => requestAnimationFrame(scrollDocumentTop));
    [80, 220, 360].forEach(delay => setTimeout(scrollDocumentTop, delay));
  });
  $("#quick-add-shortcut").addEventListener("click", focusQuickAdd);
  $("#theme-preference").addEventListener("change", event => saveThemePreference(event.currentTarget.value));
  $("#accent-color").addEventListener("input", event => {
    const color = event.currentTarget.value;
    applyAccent(accentPreference(), color);
    clearTimeout(state.accentSaveTimer);
    state.accentSaveTimer = setTimeout(() => saveCustomAccentPreference(color), 180);
  });
  $("#accent-color").addEventListener("change", event => {
    clearTimeout(state.accentSaveTimer);
    saveCustomAccentPreference(event.currentTarget.value);
  });
  $("#background-color").addEventListener("input", event => applyBackgroundColor(event.currentTarget.value, Number($("#background-strength").value), $("#background-mode").value));
  $("#background-color").addEventListener("change", event => saveBackgroundPreference(event.currentTarget.value, Number($("#background-strength").value), $("#background-mode").value));
  $("#background-strength").addEventListener("input", event => applyBackgroundColor($("#background-color").value, Number(event.currentTarget.value), $("#background-mode").value));
  $("#background-strength").addEventListener("change", event => saveBackgroundPreference($("#background-color").value, Number(event.currentTarget.value), $("#background-mode").value));
  $("#background-mode").addEventListener("change", event => saveBackgroundPreference($("#background-color").value, Number($("#background-strength").value), event.currentTarget.value));
  $("#reset-background").addEventListener("click", () => saveBackgroundPreference(null, 16, "adaptive"));
  $("#background-image-file").addEventListener("change", event => uploadBackgroundImage(event.currentTarget.files[0]));
  $("#remove-background-image").addEventListener("click", removeBackgroundImage);
  $("#background-image-opacity").addEventListener("input", event => {
    const opacity = Number(event.currentTarget.value);
    $("#background-image-opacity-value").textContent = `${opacity}%`;
    applyBackgroundImage({...state.backgroundImage, opacity});
  });
  $("#background-image-opacity").addEventListener("change", event => saveBackgroundImageOptions({opacity: Number(event.currentTarget.value)}));
  $("#background-image-tint").addEventListener("change", event => saveBackgroundImageOptions({tint: event.currentTarget.checked}));
  $("#background-image-enabled").addEventListener("change", event => saveBackgroundImageOptions({enabled: event.currentTarget.checked}));
  $("#media-artwork-tint").addEventListener("change", event => saveMediaArtworkPreference(event.currentTarget.checked));
  $("#media-artwork-full-color").addEventListener("change", event => saveMediaArtworkFullColorPreference(event.currentTarget.checked));
  $("#show-episode-progress").addEventListener("change", event => saveEpisodeProgressPreference(event.currentTarget.checked));
  [$("#icon-background-color"), $("#icon-text-color")].forEach(control => {
    control.addEventListener("input", () => {
      scheduleIconPreferenceSave($("#icon-background-color").value, $("#icon-text-color").value, $("#icon-follow-accent").checked, 180);
    });
    control.addEventListener("change", () => {
      scheduleIconPreferenceSave($("#icon-background-color").value, $("#icon-text-color").value, $("#icon-follow-accent").checked);
    });
  });
  $("#icon-follow-accent").addEventListener("change", event => {
    scheduleIconPreferenceSave($("#icon-background-color").value, $("#icon-text-color").value, event.currentTarget.checked);
  });
  $("#reset-icon-colors").addEventListener("click", () => {
    scheduleIconPreferenceSave(DEFAULT_ICON_BACKGROUND, DEFAULT_ICON_TEXT, false);
  });
  $("#search-input").addEventListener("input", () => { clearTimeout(state.searchTimer); state.searchTimer = setTimeout(runSearch, 300); });
  $("#search-type").addEventListener("change", runSearch);
  $("#quick-rating").addEventListener("input", updateQuickRefineAvailability);
  $("#quick-add-details-form").addEventListener("submit", event => {
    event.preventDefault();
    if (state.selectedResult) addSearchResult(state.selectedResult);
  });
  $("#quick-confirm-refine").addEventListener("click", () => {
    if (state.selectedResult && $("#quick-rating").value) addSearchResult(state.selectedResult, "return_existing", {refine: true});
  });
  $("#back-to-quick-add").addEventListener("click", () => {
    $("#quick-add-details-dialog").close();
    openDialog($("#quick-add-dialog"));
    setTimeout(() => $("#search-input").focus(), 50);
  });
  $("#sort").addEventListener("change", event => { state.sort = event.currentTarget.value; state.page = 1; updateSortDirectionControl(); persistNavigationState(); loadLibrary(); });
  $("#library-toolbar-search").addEventListener("input", event => {
    clearTimeout(state.librarySearchTimer);
    const value = event.currentTarget.value.trim();
    state.librarySearchTimer = setTimeout(() => {
      state.filters.q = value;
      if (!value) delete state.filters.q;
      const filterSearch = $("#filter-form [name='q']");
      if (filterSearch) filterSearch.value = value;
      state.page = 1;
      updateFilterBadge();
      persistNavigationState();
      loadLibrary({preserveScroll: true, showSkeleton: false});
    }, 180);
  });
  $("#sort-direction").addEventListener("click", event => {
    state.direction = state.direction === "desc" ? "asc" : "desc";
    updateSortDirectionControl();
    persistNavigationState();
    loadLibrary();
  });
  $("#page-size").addEventListener("change", event => {
    state.pageSize = Number(event.currentTarget.value);
    state.page = 1;
    $("#library-toolbar-search").value = state.filters.q || "";
    try { localStorage.setItem("watchtracker-page-size", String(state.pageSize)); } catch (_) { /* optional */ }
    persistNavigationState();
    loadLibrary();
  });
  $("#refresh-library").addEventListener("click", async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await loadLibrary({preserveScroll: true, showSkeleton: false});
      toast("Library refreshed");
    } finally {
      button.disabled = false;
    }
  });
  $("#dismiss-enrichment-banner").addEventListener("click", () => {
    clearTimeout(state.enrichmentBannerTimer);
    $("#enrichment-banner").hidden = true;
  });
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
  $("#filter-form").addEventListener("reset", () => setTimeout(() => { state.filters = {}; state.page = 1; $("#library-toolbar-search").value = ""; updateFilterBadge(); persistNavigationState(); loadLibrary(); }, 0));
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
        if (!(item.tmdb_movie_id || item.tmdb_tv_id || item.anilist_id || item.mal_id || Object.keys(item.external_ids || {}).length)) findEntryMetadata();
      }
      if (name === "releases" && state.currentEntry) loadEntryReleases();
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
  $("#change-media-image").addEventListener("click", openArtworkDialog);
  $("#save-media-image").addEventListener("click", () => saveArtworkSelection(state.artworkSelection));
  $("#reset-media-image").addEventListener("click", () => saveArtworkSelection(null));
  $("[data-entry-open-metadata]").addEventListener("click", () => selectEntryTab("metadata"));
  $("#find-entry-metadata").addEventListener("click", findEntryMetadata);
  $("#entry-metadata-query").addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); findEntryMetadata(); } });
  $("#next-missing-metadata").addEventListener("click", () => reviewMissingMetadata({afterCurrent: true}));
  $("#save-next-rating").addEventListener("click", saveRatingAndNext);
  $("#delete-entry").addEventListener("click", async () => {
    const id = $("#entry-id").value;
    const title = state.currentEntry?.catalog_item.canonical_title || "this entry";
    if (!await confirmAction(`Delete ${title}?`, "The entry will move to the recoverable deleted view.", "Delete entry")) return;
    try { await api(`/api/entries/${id}`, {method: "DELETE"}); $("#entry-dialog").close(); state.listsLoaded = false; toast("Entry deleted; enable Include deleted to restore it"); await loadLibrary(); $("#library-heading").focus?.(); }
    catch (error) { showMessage($("#entry-message"), error.message, true); }
  });
  $("#restore-entry").addEventListener("click", async () => {
    const id = $("#entry-id").value;
    try { await api(`/api/entries/${id}/restore`, {method: "POST"}); $("#entry-dialog").close(); state.listsLoaded = false; toast("Entry restored"); await loadLibrary({focusEntryId: id}); }
    catch (error) { showMessage($("#entry-message"), error.message, true); }
  });
  $("#open-manual").addEventListener("click", () => { $("#quick-add-dialog").close(); openDialog($("#manual-dialog")); });
  $("#manual-form").addEventListener("submit", submitManual);
  $$(".cancel-dialog").forEach(button => button.addEventListener("click", () => button.closest("dialog").close()));
  $("#open-import").addEventListener("click", openImportFromSettings);
  $("#import-form").addEventListener("submit", previewImport);
  $("#commit-form").addEventListener("submit", commitImport);
  $("#import-form [name='file']").addEventListener("change", () => { $("#preview-id").value = ""; $("#commit-form").hidden = true; $("#import-preview").innerHTML = ""; });
  $("#open-settings").addEventListener("click", openSettings);
  $("#open-account").addEventListener("click", openAccount);
  $("#open-notifications").addEventListener("click", () => switchView("notifications", {push: true, scrollTop: true}));
  $("#refresh-account-sessions").addEventListener("click", loadAccountSessions);
  $("#account-session-list").addEventListener("click", endAccountSession);
  $("#open-server-address-help").addEventListener("click", () => openDialog($("#server-address-help-dialog")));
  $$('[data-open-server-settings]').forEach(button => button.addEventListener("click", async () => {
    await openSettings();
    selectSettingsTab(button.dataset.openServerSettings);
  }));
  $("#create-list-form").addEventListener("submit", async event => {
    event.preventDefault();
    const input = $("#new-list-name");
    const name = input.value.trim();
    if (!name) return;
    try {
      await api("/api/lists", {method: "POST", body: JSON.stringify({name})});
      input.value = "";
      state.listsLoaded = false;
      await loadLists();
      toast("List created");
    } catch (error) { showMessage($("#lists-state"), error.message, true); }
  });
  $("#list-sort").value = state.listSort;
  $("#list-sort").addEventListener("change", event => {
    state.listSort = event.currentTarget.value;
    state.listsLoaded = false;
    loadLists();
  });
  $("#list-sort-direction").addEventListener("click", event => {
    state.listSortDirection = state.listSortDirection === "asc" ? "desc" : "asc";
    event.currentTarget.textContent = state.listSortDirection === "asc" ? "Oldest first" : "Newest first";
    state.listsLoaded = false;
    loadLists();
  });
  $("#back-to-lists").addEventListener("click", () => {
    state.activeListId = null;
    state.activeList = null;
    state.listsLoaded = false;
    switchView("lists", {push: true, scrollTop: true});
  });
  $("#toggle-list-navigation").addEventListener("click", async event => {
    if (!state.activeList) return;
    const button = event.currentTarget;
    button.disabled = true;
    try {
      state.activeList = await api(`/api/lists/${state.activeList.id}`, {method: "PATCH", body: JSON.stringify({pinned_to_navigation: !state.activeList.pinned_to_navigation})});
      state.listsLoaded = false;
      await Promise.all([loadListDetail(state.activeList.id), loadListNavigation()]);
      toast(state.activeList.pinned_to_navigation ? "List added to navigation" : "List removed from navigation");
    } catch (error) { showMessage($("#list-detail-state"), error.message, true); }
    finally { button.disabled = false; }
  });
  $("#delete-current-list").addEventListener("click", async () => {
    if (!state.activeList) return;
    const imported = state.activeList.source_kind === "portable";
    if (!await confirmAction(
      `${imported ? "Remove" : "Delete"} ${state.activeList.name}?`,
      imported ? "This imported shared-list snapshot will be removed. Your Library titles will not be changed." : "The list will be deleted. Its Library titles will not be changed.",
      imported ? "Remove shared list" : "Delete list"
    )) return;
    try {
      await api(`/api/lists/${state.activeList.id}`, {method: "DELETE"});
      state.activeListId = null;
      state.activeList = null;
      state.listsLoaded = false;
      await loadListNavigation();
      switchView("lists", {push: true, scrollTop: true});
      toast(imported ? "Shared list removed" : "List deleted");
    } catch (error) { showMessage($("#list-detail-state"), error.message, true); }
  });
  $("#list-detail-add-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (!state.activeList) return;
    const entryId = new FormData(event.currentTarget).get("entry_id");
    if (!entryId) return;
    try {
      await api(`/api/lists/${state.activeList.id}/entries/${entryId}`, {method: "POST", body: "{}"});
      state.listsLoaded = false;
      await loadListDetail(state.activeList.id);
      toast("Title added to list");
    } catch (error) { showMessage($("#list-detail-state"), error.message, true); }
  });
  $("#list-detail-title-search").addEventListener("focus", event => renderListTitleOptions(event.currentTarget.value));
  $("#list-detail-title-search").addEventListener("input", event => {
    $("#list-detail-add-form [name='entry_id']").value = "";
    $("#list-detail-add-form button[type='submit']").disabled = true;
    renderListTitleOptions(event.currentTarget.value);
  });
  $("#list-detail-title-search").addEventListener("keydown", event => {
    const options = $("#list-detail-title-options");
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (options.hidden) renderListTitleOptions(event.currentTarget.value);
      moveListTitlePicker(event.key === "ArrowDown" ? 1 : -1);
    } else if (event.key === "Enter" && state.listPickerIndex >= 0) {
      event.preventDefault();
      $$('[data-list-title-option]', options)[state.listPickerIndex]?.click();
    } else if (event.key === "Escape") {
      closeListTitleOptions();
    }
  });
  $("#share-list-form").addEventListener("submit", shareActiveList);
  $("#import-shared-list-form").addEventListener("submit", importSharedList);
  $$("[data-list-scope]").forEach(button => button.addEventListener("click", () => {
    state.listScope = button.dataset.listScope;
    state.listsLoaded = false;
    try { localStorage.setItem("watchtracker-list-scope", state.listScope); } catch (_) { /* optional */ }
    loadLists();
  }));
  $("#list-members").addEventListener("change", manageActiveListMember);
  $("#list-members").addEventListener("click", manageActiveListMember);
  $("#refresh-list-activity").addEventListener("click", () => loadListActivity());
  $("#refresh-list-notifications").addEventListener("click", loadListNotifications);
  $("#list-notifications").addEventListener("click", manageListNotification);
  $("#release-notifications").addEventListener("click", manageReleaseNotification);
  $("#login-dialog").addEventListener("cancel", event => event.preventDefault());
  $("#login-form").addEventListener("submit", ownerLogin);
  $("#show-local-host-recovery").addEventListener("click", () => {
    $("#login-form").hidden = true;
    $("#local-host-recovery-form").hidden = false;
    $("#show-local-host-recovery").hidden = true;
    $("#local-host-recovery-form [name='new_password']").focus();
  });
  $("#cancel-local-host-recovery").addEventListener("click", () => {
    $("#local-host-recovery-form").reset();
    $("#local-host-recovery-form").hidden = true;
    $("#login-form").hidden = false;
    $("#show-local-host-recovery").hidden = false;
    showMessage($("#login-message"), "");
  });
  $("#local-host-recovery-form").addEventListener("submit", recoverLocalServerAccount);
  $("#server-bootstrap-form").addEventListener("submit", completeServerBootstrap);
  $("#invitation-form").addEventListener("submit", redeemServerInvitation);
  $("#server-activation-form")?.addEventListener("submit", activateServer);
  $("#remote-server-discover-form").addEventListener("submit", discoverDeviceServer);
  $("#remote-server-connect-form").addEventListener("submit", connectDeviceServer);
  $("#remote-server-enroll-form").addEventListener("submit", enrollDeviceServer);
  $("#cancel-server-enrollment").addEventListener("click", () => {
    $("#server-enrollment-dialog").close();
    resetDeviceServerWizard();
  });
  $("#remote-server-back").addEventListener("click", resetDeviceServerWizard);
  $("#remote-server-connections").addEventListener("click", manageDeviceServer);
  $("#remote-server-conflicts").addEventListener("click", manageDeviceServerConflict);
  $("#server-invitation-form").addEventListener("submit", createServerInvitation);
  $("#server-user-list").addEventListener("click", manageServerUser);
  $("#rerun-server-readiness").addEventListener("click", async () => {
    try { await loadServerReadiness(); toast("Server readiness refreshed"); }
    catch (error) { showMessage($("#settings-message"), error.message, true); }
  });
  $("#logout-owner").addEventListener("click", async () => {
    if (!await confirmAction("Sign out this browser?", "Only this browser loses access to the server console. The server keeps running and no data changes.", "Sign out")) return;
    ownerSecurityAction("/api/auth/logout", {}, "Signed out");
  });
  $("#revoke-owner-sessions").addEventListener("click", async () => {
    if (!await confirmAction("Sign out the server account everywhere?", "Every browser using the server account must sign in again. Regular-user sessions and all stored data remain unchanged.", "Review sessions")) return;
    if (!await confirmAction("Confirm server-account sign-out", "This ends every current server-account session, including this browser.", "Sign out everywhere")) return;
    ownerSecurityAction("/api/auth/sessions/revoke", {}, "All server-account sessions ended");
  });
  $("#create-calendar-feed")?.addEventListener("click", createCalendarFeed);
  $("#revoke-calendar-feeds")?.addEventListener("click", revokeCalendarFeeds);
  $("#server-mode-toggle").addEventListener("change", event => {
    changeServerMode(event).catch(error => {
      event.currentTarget.checked = Boolean(state.remoteServerProfiles.find(profile => profile.enabled));
      showMessage($("#remote-server-setup-state"), error.message, true);
    });
  });
  $("#personal-tailscale-toggle").addEventListener("change", changePersonalTailscale);
  $("#owner-password-form").addEventListener("submit", event => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    ownerSecurityAction("/api/auth/password", {current_password: values.get("current_password"), new_password: values.get("new_password")}, "Password changed; sign in again");
  });
  $("#account-password-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const button = form.querySelector("button[type='submit']");
    showMessage($("#account-message"), "Changing your account password…");
    button.disabled = true;
    const changed = await ownerSecurityAction(
      "/api/auth/password",
      {current_password: values.get("current_password"), new_password: values.get("new_password")},
      "Password changed; sign in again",
      $("#account-message")
    );
    if (!changed) {
      form.elements.current_password.value = "";
      form.elements.new_password.value = "";
      button.disabled = false;
      form.elements.current_password.focus();
    }
  });
  $("#sign-out-account").addEventListener("click", async () => {
    if (!await confirmAction("Sign out this browser?", "Only this browser session ends. Your account and media data remain on the server.", "Sign out")) return;
    ownerSecurityAction("/api/auth/logout", {}, "Signed out");
  });
  $("#revoke-account-sessions").addEventListener("click", async () => {
    if (!await confirmAction("Sign out your account everywhere?", "Every browser and installed app using this regular user account must sign in again. Your account, library, ratings, notes, and lists are not deleted.", "Review sessions")) return;
    if (!await confirmAction("Confirm all-device sign-out", "This ends all current sessions for your account, including this one.", "Sign out everywhere")) return;
    ownerSecurityAction("/api/auth/sessions/revoke", {}, "All account sessions ended");
  });
  $("#settings-form").addEventListener("submit", saveSettings);
  $("#use-server-tmdb-token").addEventListener("change", event => saveServerTokenPreference(event.currentTarget.checked));
  $("#general-settings-form").addEventListener("submit", saveGeneralSettings);
  $$("#general-settings-form input, #general-settings-form select").forEach(control => {
    control.addEventListener("input", () => updateGeneralSettingsState(false));
    control.addEventListener("change", () => updateGeneralSettingsState(false));
  });
  $("#sidebar-mode").addEventListener("change", event => applySidebarPreferences(event.currentTarget.value, $("#navigation-order").value));
  $("#navigation-order").addEventListener("change", event => applySidebarPreferences($("#sidebar-mode").value, event.currentTarget.value));
  $("#interface-language").addEventListener("change", event => applyInterfaceLanguage(event.currentTarget.value, {persist: false}));
  $("#reset-general-settings").addEventListener("click", resetGeneralSettings);
  $("#advanced-ratings-enabled").addEventListener("change", event => setAdvancedRatingsEnabled(event.currentTarget.checked));
  $("#open-rankings-settings").addEventListener("click", () => { $("#settings-dialog").close(); switchView("rankings", {push: true, scrollTop: true}); loadRankings(); });
  $("#dismiss-settings-intro").addEventListener("click", async () => {
    $("#settings-intro").hidden = true;
    state.settingsPrivacyReminderDismissed = true;
    try {
      await api("/api/settings/general", {method: "PUT", body: JSON.stringify({settings_privacy_reminder_dismissed: true})});
    } catch (error) {
      state.settingsPrivacyReminderDismissed = false;
      $("#settings-intro").hidden = false;
      showMessage($("#settings-message"), error.message, true);
    }
  });
  $("#clear-tmdb").addEventListener("click", clearTmdbToken);
  $("#copy-keychain-token").addEventListener("click", copyExistingKeychainToken);
  $("#migrate-legacy-token").addEventListener("click", migrateLegacyToken);
  $("#show-token").addEventListener("change", event => { $("#tmdb-token").type = event.currentTarget.checked ? "text" : "password"; });
  $$('[data-step-for]').forEach(button => button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.stepFor);
    if (!input) return;
    const direction = Number(button.dataset.stepDirection || 1);
    const step = Number(input.step || 1);
    const min = input.min === "" ? -Infinity : Number(input.min);
    const max = input.max === "" ? Infinity : Number(input.max);
    const current = input.value === "" ? (Number.isFinite(min) ? min : 0) : Number(input.value);
    const next = input.value === "" && direction > 0 ? current : current + direction * step;
    input.value = String(Math.min(max, Math.max(min, Math.round(next * 10) / 10)));
    input.dispatchEvent(new Event("input", {bubbles: true}));
    input.dispatchEvent(new Event("change", {bubbles: true}));
  }));
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
      if (event.key === "ArrowRight" || event.key === "ArrowDown") next = (index + 1) % settingsTabs.length;
      if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = (index - 1 + settingsTabs.length) % settingsTabs.length;
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
  $("#open-import-from-settings").addEventListener("click", openImportFromSettings);
  $("#import-dialog").addEventListener("close", async () => {
    if (!state.importReturnToSettings) return;
    state.importReturnToSettings = false;
    await openSettings();
    selectSettingsTab("data");
  });
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
  $("#download-update").addEventListener("click", downloadUpdateInApp);
  $$('[data-connection-provider]').forEach(button => button.addEventListener("click", () => selectConnectionProvider(button.dataset.connectionProvider)));
  $("#start-enrichment").addEventListener("click", startEnrichment);
  $("#review-missing-metadata").addEventListener("click", () => reviewMissingMetadata());
  $("#review-ratings").addEventListener("click", () => reviewRatings());
  $("#refresh-insights").addEventListener("click", loadInsights);
  $("#refresh-currently-watching").addEventListener("click", loadCurrentlyWatching);
  $("#watching-scope").addEventListener("change", event => {
    state.watchingScope = event.currentTarget.value;
    state.currentlyWatchingLoaded = false;
    try { localStorage.setItem("watchtracker-watching-scope", state.watchingScope); } catch (_) { /* optional */ }
    persistNavigationState();
    loadCurrentlyWatching();
  });
  $("#refresh-active-shows").addEventListener("click", loadActiveShows);
  $("#sync-releases").addEventListener("click", syncAllReleases);
  $$("[data-open-calendar-page]").forEach(button => button.addEventListener("click", openReleaseCalendar));
  $("#calendar-view [data-view='active_shows']").addEventListener("click", () => switchView("active_shows", {push: true, scrollTop: true}));
  $("#release-check-mode").addEventListener("change", event => saveReleaseCheckMode(event.currentTarget.checked ? "automatic" : "manual"));
  $("#open-release-notifications").addEventListener("click", openReleaseNotifications);
  $("#refresh-rankings").addEventListener("click", loadRankings);
  $("#technical-score-help").addEventListener("click", () => openDialog($("#technical-score-dialog")));
  $("#ranking-calculation-status").addEventListener("click", event => {
    const note = $("#ranking-calculation-status-note");
    note.hidden = !note.hidden;
    event.currentTarget.setAttribute("aria-expanded", String(!note.hidden));
  });
  $("#technical-score-dialog").addEventListener("close", () => {
    $("#ranking-calculation-status-note").hidden = true;
    $("#ranking-calculation-status").setAttribute("aria-expanded", "false");
  });
  $("#refine-rankings").addEventListener("click", openRefinementScope);
  $$('[data-refinement-scope]').forEach(button => button.addEventListener("click", () => startRefinement(button.dataset.refinementScope)));
  $("#rankings-technical-mode").addEventListener("change", event => {
    state.rankingMode = event.currentTarget.checked ? "technical" : "personal";
    state.rankingsLoaded = false;
    loadRankings();
  });
  $("#rankings-filter-form").addEventListener("submit", event => { event.preventDefault(); state.rankingsLoaded = false; loadRankings(); });
  $$("#rankings-filter-form input, #rankings-filter-form select").forEach(control => control.addEventListener(control.type === "search" ? "input" : "change", () => {
    clearTimeout(state.rankingsTimer);
    state.rankingsTimer = setTimeout(() => { state.rankingsLoaded = false; loadRankings(); }, 180);
  }));
  $$('[data-insight-period]').forEach(button => button.addEventListener("click", () => {
    state.insightsFilters.period = button.dataset.insightPeriod;
    syncInsightsControls();
    if (state.insightsFilters.period !== "custom" || (state.insightsFilters.date_from && state.insightsFilters.date_to)) scheduleInsightsLoad(0);
  }));
  $$("#insights-filter-form input, #insights-filter-form select").forEach(control => control.addEventListener(control.type === "search" ? "input" : "change", event => {
    state.insightsFilters[event.currentTarget.name] = event.currentTarget.value.trim();
    if (state.insightsFilters.period === "custom" && (!state.insightsFilters.date_from || !state.insightsFilters.date_to)) return;
    scheduleInsightsLoad(event.currentTarget.type === "search" ? 220 : 0);
  }));
  $("#insights-filter-form").addEventListener("submit", event => event.preventDefault());
  $("#close-insights-drawer").addEventListener("click", () => { $("#insights-drawer").hidden = true; });
  $$("[data-record-shortcut]").forEach(button => button.addEventListener("click", () => beginShortcutCapture(button.dataset.recordShortcut)));
  $$("[data-clear-shortcut]").forEach(button => button.addEventListener("click", () => clearShortcut(button.dataset.clearShortcut)));
  $("#save-assessment-draft").addEventListener("click", async () => {
    const saved = await saveAssessmentDraft();
    if (saved && $("#assessment-dialog").open) $("#assessment-dialog").close();
  });
  $("#reset-assessment").addEventListener("click", resetAssessmentAnswers);
  $("#previous-assessment-question").addEventListener("click", previousAssessmentQuestion);
  $("#next-assessment-question").addEventListener("click", nextAssessmentQuestion);
  $("#skip-assessment-title").addEventListener("click", skipAssessmentTitle);
  $("#complete-assessment").addEventListener("click", () => completeAssessment("save_without_change"));
  $("#prefer-left").addEventListener("click", () => answerComparison("left"));
  $("#comparison-tie").addEventListener("click", () => answerComparison("tie"));
  $("#prefer-right").addEventListener("click", () => answerComparison("right"));
  $("#comparison-skip").addEventListener("click", () => answerComparison("skip"));
  $("#comparison-back").addEventListener("click", undoComparison);
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
  $("#skip-onboarding").addEventListener("click", () => completeOnboarding(null));
  document.addEventListener("keydown", event => {
    if (state.capturingShortcut) { captureShortcut(event); return; }
    const typing = event.target.matches("input, textarea, select, [contenteditable='true']");
    const openDialog = $("dialog[open]");
    if (!typing && !openDialog) {
      const signature = shortcutSignature(event);
      const action = Object.entries(state.keyboardShortcuts).find(([, value]) => value === signature)?.[0];
      if (action) { event.preventDefault(); runConfiguredShortcut(action); return; }
    }
    if (typing || openDialog || state.view !== "library") return;
    if (event.key === "ArrowLeft" && state.page > 1) { event.preventDefault(); state.page -= 1; persistNavigationState(); loadLibrary(); }
    if (event.key === "ArrowRight" && state.page < state.pages) { event.preventDefault(); state.page += 1; persistNavigationState(); loadLibrary(); }
  }, true);
  document.addEventListener("scroll", refreshHelpTooltipAfterScroll, true);
  document.addEventListener("close", hideHelpTooltip, true);
  window.addEventListener("resize", hideHelpTooltip);
  document.addEventListener("click", async event => {
    if (!event.target.closest("#list-detail-add-form")) closeListTitleOptions();
    const menu = $(".export-menu");
    if (menu?.open && !menu.contains(event.target)) menu.open = false;
    const exportLink = event.target.closest("a[href^='/api/exports/']");
    if (exportLink) {
      if (menu) menu.open = false;
      if (state.nativeWindow) {
        event.preventDefault();
        await state.appearanceSave;
        if (!window.pywebview?.api?.save_export) {
          toast("The desktop save dialog is not ready. Your library was not changed.");
          return;
        }
        try {
          const saved = await window.pywebview.api.save_export(exportLink.href);
          if (saved) toast("Export saved");
          else toast("Export was not saved");
        } catch (_) {
          toast("Export could not be saved. Your library was not changed.");
        }
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
    if (state.view === "library") loadLibrary();
  });
  window.addEventListener("pageshow", () => {
    if (state.authenticated && state.view === "library" && !state.libraryLoaded && !state.libraryLoading) loadLibrary();
  });
  setTimeout(() => {
    if (state.authenticated && state.view === "library" && !state.libraryLoaded && !state.libraryLoading) loadLibrary();
  }, 1200);
  initializeAuthentication().then(async authenticated => {
    if (!authenticated) return;
    let experience;
    try { experience = await configureAuthenticatedExperience(); }
    catch (error) {
      showMessage($("#login-message"), error.message, true);
      showOwnerLogin();
      return;
    }
    if (experience === "server-owner") return;
    const requestedSettings = new URLSearchParams(window.location.search).get("open_settings");
    if (requestedSettings === "access" && state.accessMode === "local") {
      await openSettings();
      selectSettingsTab("access");
    }
    if (!state.libraryLoading) loadLibrary();
    loadListNavigation();
    pollEnrichment();
    if (state.accessMode === "local" && requestedSettings !== "access") initializeOnboarding();
    api("/api/settings/general").then(data => renderGeneralSettings(data)).catch(() => {});
  });
});
