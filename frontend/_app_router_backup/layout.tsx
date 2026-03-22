import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'AI Command Center',
  description: 'Sci-fi task management interface for AI coding sessions',
  icons: {
    icon: [
      {
        url: '/icon-light-32x32.png',
        media: '(prefers-color-scheme: light)',
      },
      {
        url: '/icon-dark-32x32.png',
        media: '(prefers-color-scheme: dark)',
      },
      {
        url: '/icon.svg',
        type: 'image/svg+xml',
      },
    ],
    apple: '/apple-icon.png',
  },
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en">
      <head>
        <script src="/eel.js" type="text/javascript"></script>
      </head>
      <body className="font-sans antialiased">
        {children}
      </body>
    </html>
  )
}
