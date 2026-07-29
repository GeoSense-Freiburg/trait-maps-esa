const escapeHtml = (value) =>
  String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

const externalUrl = (value) => {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
};

const linkForRelation = (collection, relation) =>
  collection.links?.find((link) => link.rel === relation)?.href ?? null;

const compactCitation = (citation) => {
  const author = citation?.match(/^([^,]+)/)?.[1];
  const year = citation?.match(/\((\d{4})\)/)?.[1];
  return author && year ? `${author} et al. (${year})` : citation || "—";
};

const collectionFacts = (collection) => {
  const description = collection.description ?? "";
  const resolution =
    description.match(/(\d+(?:\.\d+)?\s*km) resolution/i)?.[1] ?? "—";
  const traitCount =
    description.match(/(?:\(|\b)(\d+) traits(?:\)|\b)/i)?.[1] ?? "—";
  const bbox = collection.extent?.spatial?.bbox?.[0];
  const isGlobal =
    bbox?.[0] <= -180 &&
    bbox?.[1] <= -90 &&
    bbox?.[2] >= 180 &&
    bbox?.[3] >= 90;

  return {
    resolution,
    traitCount,
    coverage: isGlobal ? "Global" : "Collection extent",
  };
};

const resourceLink = (href, label) => {
  const url = externalUrl(href);
  if (!url) return "";
  return `<a class="dataset-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" aria-label="${escapeHtml(label)} (opens in a new tab)">${escapeHtml(label)}<span aria-hidden="true"> ↗</span></a>`;
};

export const datasetInformationMarkup = (collection) => {
  const facts = collectionFacts(collection);
  const doi = collection["sci:doi"] ?? "—";
  const citation = collection["sci:citation"] ?? "";
  const datasetUrl =
    externalUrl(linkForRelation(collection, "via")) ??
    externalUrl(linkForRelation(collection, "cite-as")) ??
    (doi !== "—" ? externalUrl(`https://doi.org/${doi}`) : null);
  const publicationUrl = linkForRelation(collection, "describedby");
  const summary = `Global ${facts.resolution} maps of ${facts.traitCount} plant functional traits derived from biodiversity observations, vegetation surveys, plant trait measurements and Earth observation data.`;

  return `
    <h1 class="visually-hidden">Global Plant Trait Maps Explorer</h1>
    <section class="dataset-card" aria-labelledby="dataset-information-title">
      <div class="dataset-card-head">
        <h2 id="dataset-information-title">Dataset information</h2>
        <button id="collapse-dataset-information" class="collapse dataset-collapse" type="button" aria-expanded="true" aria-controls="dataset-information-body" aria-label="Minimize dataset information" title="Minimize">−</button>
      </div>
      <div id="dataset-information-body" class="dataset-card-body">
        <p class="dataset-summary">${escapeHtml(summary)}</p>
        <dl class="dataset-metadata">
          <div><dt>Spatial coverage</dt><dd>${escapeHtml(facts.coverage)}</dd></div>
          <div><dt>Spatial resolution</dt><dd>${escapeHtml(facts.resolution)}</dd></div>
          <div><dt>Number of traits</dt><dd>${escapeHtml(facts.traitCount)}</dd></div>
          <div class="metadata-wide"><dt>DOI</dt><dd>${
            datasetUrl
              ? `<a href="${escapeHtml(datasetUrl)}" target="_blank" rel="noopener noreferrer" aria-label="Dataset DOI ${escapeHtml(doi)} (opens in a new tab)">${escapeHtml(doi)}</a>`
              : escapeHtml(doi)
          }</dd></div>
          <div class="metadata-wide"><dt>Citation</dt><dd><cite aria-label="${escapeHtml(citation || compactCitation(citation))}">${escapeHtml(compactCitation(citation))}</cite></dd></div>
        </dl>
        <nav class="dataset-links" aria-label="Dataset resources">
          ${resourceLink(publicationUrl, "View publication")}
          ${resourceLink(datasetUrl, "Download dataset")}
        </nav>
      </div>
    </section>`;
};
