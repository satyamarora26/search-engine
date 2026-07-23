import { Play } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'

export type WikipediaCrawlFormValues = {
  source: 'wikipedia'
  category: string
  max_articles: number
  max_depth: number
}

export type MediumCrawlFormValues = {
  source: 'medium'
  publication_url: string
  max_articles: number
  max_depth: 0
}

export type RssCrawlFormValues = {
  source: 'rss'
  feed_url: string
  max_articles: number
  max_depth: 0
}

export type CrawlFormValues = WikipediaCrawlFormValues | MediumCrawlFormValues | RssCrawlFormValues
export type CrawlSource = CrawlFormValues['source']

type CrawlFormProps = {
  isSubmitting?: boolean
  onSubmit: (values: CrawlFormValues) => void
}

type FormValues = {
  source: CrawlSource
  category: string
  publication_url: string
  feed_url: string
  max_articles: string
  max_depth: string
}

type FormErrors = Partial<Record<keyof FormValues, string>>

const DEFAULT_CRAWL_FORM: FormValues = {
  source: 'wikipedia',
  category: 'Featured articles',
  publication_url: 'https://medium.com/towards-data-science',
  feed_url: 'https://feeds.bbci.co.uk/news/rss.xml',
  max_articles: '100',
  max_depth: '0',
}

function isMediumPublicationUrl(value: string): boolean {
  try {
    const url = new URL(value)
    const host = url.hostname.toLowerCase()
    const segments = url.pathname.split('/').filter(Boolean)
    const isMediumHost = host === 'medium.com' || host.endsWith('.medium.com')
    if (url.protocol !== 'https:' || !isMediumHost || url.username || url.password || url.search || url.hash) {
      return false
    }
    if (host === 'medium.com') return segments.length === 1 && segments[0] !== 'p' && !segments[0].startsWith('@')
    return segments.length <= 1 && !segments.some((segment) => segment.startsWith('@'))
  } catch {
    return false
  }
}

function isRssFeedUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && Boolean(url.hostname) && !url.username && !url.password
  } catch {
    return false
  }
}

export function CrawlForm({ isSubmitting = false, onSubmit }: CrawlFormProps) {
  const [values, setValues] = useState(DEFAULT_CRAWL_FORM)
  const [errors, setErrors] = useState<FormErrors>({})

  function updateValue(field: keyof FormValues, value: string) {
    setValues((current) => ({ ...current, [field]: value }))
    setErrors((current) => ({ ...current, [field]: undefined }))
  }

  function handleSourceChange(source: CrawlSource) {
    setValues((current) => ({
      ...current,
      source,
      max_depth: source === 'wikipedia' ? current.max_depth : '0',
    }))
    setErrors({})
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const nextErrors: FormErrors = {}
    const maxArticles = Number(values.max_articles)

    if (!Number.isInteger(maxArticles) || maxArticles < 1 || maxArticles > 500) {
      nextErrors.max_articles = 'Use a value between 1 and 500.'
    }

    if (values.source === 'medium') {
      const publicationUrl = values.publication_url.trim()
      if (!isMediumPublicationUrl(publicationUrl)) {
        nextErrors.publication_url = 'Enter a public Medium publication URL.'
      }
      if (Object.keys(nextErrors).length > 0) {
        setErrors(nextErrors)
        return
      }
      onSubmit({
        source: 'medium',
        publication_url: publicationUrl,
        max_articles: maxArticles,
        max_depth: 0,
      })
      return
    }

    if (values.source === 'rss') {
      const feedUrl = values.feed_url.trim()
      if (!isRssFeedUrl(feedUrl)) {
        nextErrors.feed_url = 'Enter a public HTTPS RSS or Atom feed URL.'
      }
      if (Object.keys(nextErrors).length > 0) {
        setErrors(nextErrors)
        return
      }
      onSubmit({
        source: 'rss',
        feed_url: feedUrl,
        max_articles: maxArticles,
        max_depth: 0,
      })
      return
    }

    const category = values.category.trim()
    const maxDepth = Number(values.max_depth)
    if (!category) nextErrors.category = 'Enter a category title.'
    if (!Number.isInteger(maxDepth) || maxDepth < 0 || maxDepth > 2) {
      nextErrors.max_depth = 'Use a value between 0 and 2.'
    }

    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors)
      return
    }

    onSubmit({
      source: 'wikipedia',
      category,
      max_articles: maxArticles,
      max_depth: maxDepth,
    })
  }

  const isMedium = values.source === 'medium'
  const isRss = values.source === 'rss'
  const isBoundedSource = isMedium || isRss

  return (
    <form className="crawl-form" aria-label="Crawl form" noValidate onSubmit={handleSubmit}>
      <div className="crawl-form-fields">
        <label className="form-field form-field-wide" htmlFor="crawl-source">
          <span>Crawl source</span>
          <select
            id="crawl-source"
            value={values.source}
            onChange={(event) => handleSourceChange(event.target.value as CrawlSource)}
          >
            <option value="wikipedia">Wikipedia</option>
            <option value="medium">Medium publication</option>
            <option value="rss">RSS or Atom feed</option>
          </select>
        </label>

        {isMedium ? (
          <label className="form-field form-field-wide" htmlFor="crawl-publication-url">
            <span>Publication URL</span>
            <input
              id="crawl-publication-url"
              type="url"
              value={values.publication_url}
              onChange={(event) => updateValue('publication_url', event.target.value)}
              aria-invalid={Boolean(errors.publication_url)}
              aria-describedby={errors.publication_url ? 'crawl-publication-url-error' : undefined}
              placeholder="https://medium.com/towards-data-science"
            />
            {errors.publication_url && <small id="crawl-publication-url-error" className="field-error">{errors.publication_url}</small>}
          </label>
        ) : isRss ? (
          <label className="form-field form-field-wide" htmlFor="crawl-feed-url">
            <span>Feed URL</span>
            <input
              id="crawl-feed-url"
              type="url"
              value={values.feed_url}
              onChange={(event) => updateValue('feed_url', event.target.value)}
              aria-invalid={Boolean(errors.feed_url)}
              aria-describedby={errors.feed_url ? 'crawl-feed-url-error' : undefined}
              placeholder="https://example.com/feed.xml"
            />
            {errors.feed_url && <small id="crawl-feed-url-error" className="field-error">{errors.feed_url}</small>}
          </label>
        ) : (
          <label className="form-field form-field-wide" htmlFor="crawl-category">
            <span>Category</span>
            <input
              id="crawl-category"
              value={values.category}
              onChange={(event) => updateValue('category', event.target.value)}
              aria-invalid={Boolean(errors.category)}
              aria-describedby={errors.category ? 'crawl-category-error' : undefined}
              placeholder="Featured articles"
            />
            {errors.category && <small id="crawl-category-error" className="field-error">{errors.category}</small>}
          </label>
        )}

        <label className="form-field" htmlFor="crawl-max-articles">
          <span>Maximum articles</span>
          <input
            id="crawl-max-articles"
            type="number"
            min="1"
            max="500"
            step="1"
            value={values.max_articles}
            onChange={(event) => updateValue('max_articles', event.target.value)}
            aria-invalid={Boolean(errors.max_articles)}
            aria-describedby={errors.max_articles ? 'crawl-max-articles-error' : undefined}
          />
          {errors.max_articles && <small id="crawl-max-articles-error" className="field-error">{errors.max_articles}</small>}
        </label>

        <label className="form-field" htmlFor="crawl-max-depth">
          <span>Maximum depth</span>
          <input
            id="crawl-max-depth"
            type="number"
            min="0"
            max={isBoundedSource ? 0 : 2}
            step="1"
            value={isBoundedSource ? 0 : values.max_depth}
            onChange={(event) => updateValue('max_depth', event.target.value)}
            aria-invalid={Boolean(errors.max_depth)}
            aria-describedby={errors.max_depth ? 'crawl-max-depth-error' : undefined}
            disabled={isBoundedSource}
          />
          {errors.max_depth && <small id="crawl-max-depth-error" className="field-error">{errors.max_depth}</small>}
        </label>
      </div>

      <div className="crawl-form-footer">
        <p>{isMedium ? 'Medium discovery uses permitted RSS and sitemap metadata for one publication.' : isRss ? 'RSS and Atom feeds are bounded to one feed and its same-host article links.' : 'Category titles are normalized by the API before discovery begins.'}</p>
        <button className="button button-primary" type="submit" disabled={isSubmitting}>
          <Play size={15} aria-hidden="true" />
          {isSubmitting ? 'Starting crawl...' : 'Start crawl'}
        </button>
      </div>
    </form>
  )
}

export function WikipediaCrawlForm(props: CrawlFormProps) {
  return <CrawlForm {...props} />
}
