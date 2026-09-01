# Paper repository discovery

Read the converted paper at `{{ paper_markdown }}` and write exactly one JSON
object to `{{ candidates_path }}`:

```json
{
  "repositories": [
    {
      "url": "https://github.com/owner/project",
      "evidence": "The exact paper text that directly discloses this source repository URL.",
      "revision": null
    }
  ]
}
```

The list may be empty. Include every source-code Git repository URL directly
disclosed by the paper, in paper order. The `url` must occur verbatim in the
paper Markdown and must be an HTTPS URL that identifies a Git repository.
Record a revision only when the disclosed URL itself pins a branch, tag, or
commit.

Do not browse the web, follow redirects, resolve DOI/OSF/Zenodo/publisher pages,
infer a repository from the paper title or authors, or invent/correct a URL.
Do not include dataset downloads, project home pages, documentation sites,
package registries, model hubs, or supplementary files unless the paper itself
directly identifies the HTTPS URL as its source-code Git repository. Reload the
written JSON before finishing and confirm that every URL appears verbatim in
the paper.
