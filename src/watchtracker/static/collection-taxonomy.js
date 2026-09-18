/* Display labels only. Never feed these summaries back into saved metadata. */
(() => {
  "use strict";
  const bookLabels = [
    ["Science fiction", /\b(science[ -]fiction|sci[ -]?fi)\b/i],
    ["Fantasy", /\bfantas(?:y|ies|tique)\b/i],
    ["Mystery", /\b(mystery|mysteries|detective)\b/i],
    ["Thriller", /\b(thrillers?|suspense)\b/i],
    ["Horror", /\bhorror\b/i],
    ["Romance", /\bromance\b/i],
    ["Historical fiction", /\bhistorical fiction\b/i],
    ["Literary fiction", /\bliterary(?: fiction)?\b/i],
    ["Speculative fiction", /\bspeculative fiction\b/i],
    ["Dystopian fiction", /\bdystopi(?:an|as?)\b/i],
    ["Psychological fiction", /\b(psychological fiction|fiction, psychological)\b/i],
    ["Magical realism", /\bmagic(?:al)? realism\b/i],
    ["Gothic", /\bgothic\b/i],
    ["Western", /\bwesterns?\b/i],
    ["Coming of age", /\b(coming[ -]of[ -]age|bildungsroman?s?)\b/i],
    ["War fiction", /\b(war stories|military fiction|war fiction|fiction, war)\b/i],
    ["Biography", /\b(biography|biographies|biographical)\b/i],
    ["Memoir", /\b(memoirs?|autobiograph(?:y|ies))\b/i],
    ["Poetry", /\b(poetry|poems)\b/i],
    ["Drama", /\b(drama|plays)\b/i],
    ["Comics", /\b(comics|graphic novels?)\b/i],
    ["Manga", /\bmanga\b/i],
    ["Adventure", /\badventure\b/i],
    ["Humor", /\b(humou?r(?:ous)?|comedy|satire|satirical)\b/i],
    ["Science", /\bscience\b/i],
    ["History", /\bhistory\b/i],
    ["Philosophy", /\bphilosophy\b/i],
    ["Psychology", /\bpsychology\b/i],
    ["Religion", /\b(religion|spirituality)\b/i],
    ["Self-help", /\bself[ -]help\b/i],
    ["Business", /\b(business|economics)\b/i],
    ["Technology", /\b(technology|computers|programming)\b/i],
    ["Cooking", /\b(cooking|cookbooks|cookery)\b/i],
    ["Travel", /\btravel\b/i],
    ["Art", /\b(art|photography)\b/i],
    ["Music", /\bmusic\b/i],
    ["Essays", /\bessays\b/i],
    ["Young adult", /\byoung adult\b/i],
    ["Children’s books", /\b(children'?s|juvenile)\b/i],
    ["Nonfiction", /\bnon[ -]?fiction\b/i],
    ["Fiction", /\bfiction\b/i]
  ];
  const musicLabels = [
    ["R&B", /\b(r&b|rhythm and blues)\b/i],
    ["Hip-hop", /\b(hip[ -]?hop|rap)\b/i],
    ["Jazz", /\bjazz\b/i], ["Rock", /\brock\b/i],
    ["Pop", /\bpop\b/i], ["Electronic", /\b(electronic|electronica|edm|techno|house|synth[ -]?pop)\b/i],
    ["Folk", /\bfolk\b/i], ["Soul", /\bsoul\b/i],
    ["Classical", /\b(classical|orchestral|baroque)\b/i],
    ["Country", /\bcountry\b/i], ["Blues", /\bblues\b/i],
    ["Metal", /\bmetal\b/i], ["Punk", /\bpunk\b/i],
    ["Reggae", /\breggae\b/i], ["Ambient", /\bambient\b/i],
    ["Soundtrack", /\b(soundtracks?|film score)\b/i],
    ["Latin", /\b(latin|salsa|bossa nova)\b/i], ["Funk", /\bfunk\b/i],
    ["Disco", /\bdisco\b/i], ["Gospel", /\bgospel\b/i]
  ];
  const sourceValues = values => Array.isArray(values) ? values.filter(value => typeof value === "string") : [];
  const clean = value => value.normalize("NFKC").replace(/[_\s]+/g, " ").trim();
  const topicOnly = value => /\b(imaginary place|fictitious character|fictional character|bombing of|battle of|siege of|criticism and interpretation|study and teaching)\b/i.test(value)
    || /^(popular works|general|accessible book|protected daisy|in library|large type books)$/i.test(value)
    || /^(place|person|time|nyt|award):/i.test(value)
    || /\b(bestseller|staff picks|award winner|new york times reviewed|reading level)\b/i.test(value);
  function compact(value) {
    const label = clean(value).replace(/\s*\([^)]*\)\s*/g, " ").replace(/\s+/g, " ").trim();
    if (label.length <= 30) return label;
    const fragment = label.slice(0, 28).replace(/\s+\S*$/, "").trim() || label.slice(0, 28);
    return `${fragment}…`;
  }
  function labelsFor(raw, mode, subgenre) {
    const value = clean(raw);
    if (!value || topicOnly(value)) return [];
    if (subgenre) {
      // Recognize explicit catalog paths, not a hierarchy inferred from a title.
      if (/\bregency\b/i.test(value) && /\bromance\b/i.test(value)) return ["Regency romance"];
      if (/\bhistorical\b/i.test(value) && /\bromance\b/i.test(value)) return ["Historical romance"];
      if (/[;,/]/.test(value)) {
        const parts = value.split(/[,;/]/).map(clean).filter(part => !/^(fiction|nonfiction|general)$/i.test(part));
        if (parts.length) return [compact(parts[parts.length - 1])];
      }
      return [compact(value)];
    }
    const labels = (mode === "books" ? bookLabels : musicLabels).filter(([, matcher]) => matcher.test(value)).map(([label]) => label);
    if (labels.includes("Science fiction") && labels.includes("Science")) labels.splice(labels.indexOf("Science"), 1);
    if (labels.includes("R&B") && labels.includes("Blues")) labels.splice(labels.indexOf("Blues"), 1);
    if (labels.length > 1 && labels.includes("Fiction")) labels.splice(labels.indexOf("Fiction"), 1);
    return labels.length ? labels : [compact(value)];
  }
  function project(values, mode, subgenre, providerLinked) {
    const result = new Map();
    const recognized = new Set();
    for (const raw of values) for (const label of labelsFor(raw, mode, subgenre)) {
      if (!label) continue;
      const key = label.toLocaleLowerCase("en");
      if (mode === "books" && !subgenre && bookLabels.some(([, matcher]) => matcher.test(clean(raw)))) recognized.add(key);
      if (!result.has(key)) result.set(key, {label, raw: []});
      const item = result.get(key);
      if (!item.raw.includes(raw)) item.raw.push(raw);
    }
    // Open Library's subjects include characters, awards and settings. Unknown
    // subjects stay in Metadata, not in genre chips. Custom/manual-only labels
    // remain usable when no recognized classification exists.
    if (mode === "books" && !subgenre && (providerLinked || recognized.size)) {
      for (const key of result.keys()) if (!recognized.has(key)) result.delete(key);
    }
    // A generic Fiction chip need not compete with an explicit fiction genre.
    if (["science fiction", "fantasy", "mystery", "thriller", "horror", "romance", "historical fiction", "literary fiction", "speculative fiction", "dystopian fiction", "psychological fiction", "magical realism", "gothic", "western", "coming of age", "war fiction"].some(key => result.has(key))) result.delete("fiction");
    return [...result.values()];
  }
  function summarize(row, mode) {
    const sourceGenres = [...sourceValues(row?.genres)];
    const sourceSubgenres = [...sourceValues(row?.subgenres)];
    const effective = (values, subgenre) => {
      const prefix = subgenre ? "subgenre" : "genre";
      const removed = new Set(sourceValues(row?.[`${prefix}_removals`]).map(value => value.toLocaleLowerCase("en")));
      const entries = project(values.filter(value => !removed.has(value.toLocaleLowerCase("en"))), mode, subgenre, Boolean(row?.provider_id)).filter(term => !removed.has(term.label.toLocaleLowerCase("en")));
      for (const value of sourceValues(row?.[`${prefix}_additions`])) if (!entries.some(term => term.label.toLocaleLowerCase("en") === value.toLocaleLowerCase("en"))) entries.push({label: value, raw: [value]});
      return entries;
    };
    return {genres: effective(sourceGenres, false), subgenres: effective(sourceSubgenres, true), sourceGenres, sourceSubgenres};
  }
  const translationKeys = new Map();
  function label(value, language = document.documentElement.lang || "en") {
    // Genre names must not pass through workspace copy substitution (e.g.
    // a book about Music is not the genre "Books") or reverse UI translation.
    if (language === "en") return capitalize(value);
    const key = clean(String(value)).toLocaleLowerCase("en");
    if (language === "fr" && key === "history") return "Histoire";
    if (language === "fr" && key === "drama") return "Drame";
    const dictionary = window.PMT_LOCALES?.[language] || {};
    if (!translationKeys.has(language)) translationKeys.set(language, new Map(Object.keys(dictionary).map(term => [clean(term).toLocaleLowerCase("en"), term])));
    return capitalize(dictionary[translationKeys.get(language).get(key)] || value, language);
  }
  function capitalize(value, language = document.documentElement.lang || "en") {
    // Presentation only: retain acronyms, internal capitals and source spelling.
    return String(value).replace(/\p{L}/u, character => character.toLocaleUpperCase(language));
  }
  window.PMTCollectionTaxonomy = Object.freeze({summarize, label, capitalize});
})();
