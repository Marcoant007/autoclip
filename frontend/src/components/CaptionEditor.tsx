import { useEffect, useState } from 'react'

import { formatTimecode, type Word } from '../api'
import { Icon, Spinner } from './Icon'

/**
 * Word-level caption editing.
 *
 * The job here is fixing what Whisper misheard — names, jargon, acronyms. Only
 * the text is editable; timings stay locked to the measured audio, because a
 * hand-typed timestamp is how captions drift out of sync.
 */
export function CaptionEditor({
  words,
  onChange,
  onSave,
  saving,
  dirty,
}: {
  words: Word[]
  onChange: (words: Word[]) => void
  onSave: () => void
  saving: boolean
  dirty: boolean
}) {
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState('')

  useEffect(() => setEditing(null), [words.length])

  const commit = (index: number) => {
    const text = draft.trim()
    if (text && text !== words[index].text) {
      const next = words.map((word, i) => (i === index ? { ...word, text } : word))
      onChange(next)
    }
    setEditing(null)
  }

  if (words.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-ink-500">
        Ainda não há transcrição para este corte.
      </p>
    )
  }

  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="label">Texto da legenda</p>
          <p className="mt-0.5 text-xs text-ink-500">
            Clique numa palavra para corrigir. <kbd className="rounded bg-ink-800 px-1">Tab</kbd> vai para a próxima.
          </p>
        </div>
        <span className="numeric chip shrink-0">{words.length} palavras</span>
      </div>

      {/* Words flow as text, not as a list of rows — reading it back is the
          main way you notice a mistranscription. */}
      <div className="mt-4 max-h-[40vh] overflow-y-auto rounded-xl bg-ink-900 p-4 text-[0.9375rem] leading-[1.95]">
        {words.map((word, index) =>
          editing === index ? (
            <input
              key={index}
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={() => commit(index)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commit(index)
                if (e.key === 'Escape') setEditing(null)
                if (e.key === 'Tab') {
                  e.preventDefault()
                  commit(index)
                  const next = index + (e.shiftKey ? -1 : 1)
                  if (next >= 0 && next < words.length) {
                    setDraft(words[next].text)
                    setEditing(next)
                  }
                }
              }}
              className="mr-1 w-[8ch] border-b border-accent-500 bg-transparent px-0.5 text-ink-100 outline-none"
              style={{ width: `${Math.max(4, draft.length + 1)}ch` }}
            />
          ) : (
            <button
              key={index}
              onClick={() => {
                setDraft(word.text)
                setEditing(index)
              }}
              title={formatTimecode(word.start)}
              className="mr-1 rounded-[2px] px-0.5 text-ink-200 transition-colors duration-150 hover:bg-accent-700/25 hover:text-ink-100"
            >
              {word.text}
            </button>
          ),
        )}
      </div>

      <div className="mt-4 flex items-center gap-4">
        <button onClick={onSave} disabled={!dirty || saving} className="btn btn-primary">
          {saving ? <Spinner /> : <Icon name="save" size={15} />}
          {saving ? 'Salvando…' : 'Salvar correções'}
        </button>
        <span className={`text-xs ${dirty ? 'text-signal-warn' : 'text-ink-500'}`}>
          {dirty ? 'Há correções não salvas' : 'Nenhuma alteração pendente'}
        </span>
      </div>
    </div>
  )
}
