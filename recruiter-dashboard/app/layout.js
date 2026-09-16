import './globals.css'

export const metadata = {
  title: 'Recruiter Dashboard',
  description: 'Review and approve recruiter-outreach triage drafts',
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
