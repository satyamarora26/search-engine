import { Play } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'

export type CrawlFormValues = {
  category: string
  max_articles: number
  max_depth: number
}

type CrawlFormProps = {
  isSubmitting?: boolean
  onSubmit: (values: CrawlFormValues) => void
}

type FormValues = {
  category: string
  max_articles: string
  max_depth: string
}

type FormErrors = Partial<Record<keyof FormValues, string>>

const DEFAULT_CRAWL_FORM: FormValues = {
  category: 'Featured articles',
  max_articles: '100',
  max_depth: '0',
}

export function WikipediaCrawlForm({ isSubmitting = false, onSubmit }: CrawlFormProps) {
  const [values, setValues] = useState(DEFAULT_CRAWL_FORM)
  const [errors, setErrors] = useState<FormErrors>({})

  function updateValue(field: keyof FormValues, value: string) {
    setValues((current) => ({ ...current, [field]: value }))
    setErrors((current) => ({ ...current, [field]: undefined }))
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const nextErrors: FormErrors = {}
    const category = values.category.trim()
    const maxArticles = Number(values.max_articles)
    const maxDepth = Number(values.max_depth)

    if (!category) nextErrors.category = 'Enter a category title.'
    if (!Number.isInteger(maxArticles) || maxArticles < 1 || maxArticles > 500) {
      nextErrors.max_articles = 'Use a value between 1 and 500.'
    }
    if (!Number.isInteger(maxDepth) || maxDepth < 0 || maxDepth > 2) {
      nextErrors.max_depth = 'Use a value between 0 and 2.'
    }

    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors)
      return
    }

    onSubmit({
      category,
      max_articles: maxArticles,
      max_depth: maxDepth,
    })
  }

  return (
    <form className="crawl-form" aria-label="Wikipedia crawl form" noValidate onSubmit={handleSubmit}>
      <div className="crawl-form-fields">
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
            max="2"
            step="1"
            value={values.max_depth}
            onChange={(event) => updateValue('max_depth', event.target.value)}
            aria-invalid={Boolean(errors.max_depth)}
            aria-describedby={errors.max_depth ? 'crawl-max-depth-error' : undefined}
          />
          {errors.max_depth && <small id="crawl-max-depth-error" className="field-error">{errors.max_depth}</small>}
        </label>
      </div>

      <div className="crawl-form-footer">
        <p>Category titles are normalized by the API before discovery begins.</p>
        <button className="button button-primary" type="submit" disabled={isSubmitting}>
          <Play size={15} aria-hidden="true" />
          {isSubmitting ? 'Starting crawl...' : 'Start crawl'}
        </button>
      </div>
    </form>
  )
}
