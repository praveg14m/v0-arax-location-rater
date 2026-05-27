export default function Home() {
  return (
    <main className="min-h-screen">
      <div className="mx-auto max-w-5xl px-8 py-24">
        <p className="eyebrow mb-6">Arax Properties · Internal Tool</p>
        <h1 className="font-serif text-5xl tracking-tight" style={{ color: "var(--color-navy)" }}>
          Location Rater
        </h1>
        <div className="mt-6 h-px w-16" style={{ backgroundColor: "var(--color-bronze)" }} />
        <p className="mt-8 max-w-xl text-[15px] leading-relaxed" style={{ color: "var(--color-body)" }}>
          Project scaffold ready. Design tokens, typography, Python serverless function routing, and Vercel Blob
          storage are configured. Awaiting next instruction to build the upload-and-score workflow.
        </p>
      </div>
    </main>
  )
}
