export default function PlaceholderPage({ title }: { title: string }) {
  return (
    <section className="placeholder-page">
      <p className="eyebrow">LiftLog</p>
      <h1>{title}</h1>
      <p>Screen build follows in the next migration increment.</p>
    </section>
  )
}
