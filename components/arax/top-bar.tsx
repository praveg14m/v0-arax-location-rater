export function TopBar() {
  return (
    <header className="w-full">
      <div className="mx-auto max-w-7xl px-8 py-6">
        <div className="flex items-center">
          <span
            className="text-[15px]"
            style={{ color: "var(--color-navy)", letterSpacing: "0.15em" }}
          >
            <span className="font-bold">ARAX</span>
            <span className="font-normal"> PROPERTIES</span>
          </span>
        </div>
      </div>
      <div className="h-px w-full" style={{ backgroundColor: "var(--color-bronze)" }} />
    </header>
  )
}
