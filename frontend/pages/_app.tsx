import type { AppProps } from 'next/app'
import Head from 'next/head'
import '../_app_router_backup/globals.css'

export default function App({ Component, pageProps }: AppProps) {
  return (
    <>
      <Head>
        <title>AI Command Center</title>
        <meta name="description" content="Sci-fi task management interface for AI coding sessions" />
        <script src="/eel.js" />
      </Head>
      <Component {...pageProps} />
    </>
  )
}
