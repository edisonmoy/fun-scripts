#!/usr/bin/env node
import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const ansi = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  gray: '\x1b[90m',
  purple: '\x1b[38;5;141m',
  cyan: '\x1b[36m'
}

const streamColors = [
  '\x1b[36m',
  '\x1b[35m',
  '\x1b[33m',
  '\x1b[34m',
  '\x1b[32m',
  '\x1b[38;5;208m'
]

const isTTY = Boolean(process.stdout.isTTY)
const overallStartedAt = performance.now()

const NORMALIZE_FILTER =
  'scale=iw*min(1920/iw\\,1080/ih):ih*min(1920/iw\\,1080/ih),' +
  'pad=1920:1080:(1920-iw*min(1920/iw\\,1080/ih))/2:(1080-ih*min(1920/iw\\,1080/ih))/2,' +
  'format=yuv420p'

function expandTilde(filePath) {
  if (filePath === '~') return os.homedir()
  if (filePath.startsWith('~/')) return path.join(os.homedir(), filePath.slice(2))
  return filePath
}

function getStreamColor(index) {
  return streamColors[index % streamColors.length]
}

function formatDuration(ms) {
  if (!Number.isFinite(ms)) return '0ms'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatSize(bytes) {
  const magnitude = Math.abs(bytes)
  const sign = bytes < 0 ? '-' : ''
  if (magnitude < 1024) return `${sign}${magnitude} B`
  if (magnitude < 1024 * 1024) return `${sign}${(magnitude / 1024).toFixed(1)} KB`
  return `${sign}${(magnitude / (1024 * 1024)).toFixed(1)} MB`
}

function localTimestamp() {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  return [
    now.getFullYear(),
    pad(now.getMonth() + 1),
    pad(now.getDate()),
    '_',
    pad(now.getHours()),
    pad(now.getMinutes()),
    pad(now.getSeconds())
  ].join('')
}

function fileSize(filePath) {
  try {
    return fs.statSync(filePath).size
  } catch {
    return 0
  }
}

function terminalWidth() {
  const columns = process.stdout.columns
  return Number.isInteger(columns) && columns > 20 ? columns : 80
}

function clip(text, maxWidth) {
  if (maxWidth <= 0) return ''
  if (text.length <= maxWidth) return text
  return `${text.slice(0, maxWidth - 1)}…`
}

const rawFiles = process.argv.slice(2)
if (rawFiles.length === 0) {
  console.error(`${ansi.red}Usage: vcc <video1> [video2...]${ansi.reset}`)
  process.exit(1)
}

const files = rawFiles.map((file) => path.resolve(expandTilde(file)))
const missing = files.filter((file) => !fs.existsSync(file))
if (missing.length > 0) {
  for (const file of missing) console.error(`${ansi.red}Not found:${ansi.reset} ${file}`)
  process.exit(1)
}

function probeInput(file) {
  const probe = spawnSync(
    'ffprobe',
    [
      '-v',
      'error',
      '-show_entries',
      'format=duration:stream=codec_type',
      '-of',
      'json',
      file
    ],
    { encoding: 'utf8' }
  )
  if (probe.status !== 0) return null
  try {
    const parsed = JSON.parse(probe.stdout)
    const duration = Number.parseFloat(parsed.format?.duration ?? '')
    return {
      durationSeconds: Number.isFinite(duration) ? duration : null,
      hasAudio: (parsed.streams ?? []).some((stream) => stream.codec_type === 'audio')
    }
  } catch {
    return null
  }
}

const inputs = files.map((absolutePath, index) => {
  const probe = probeInput(absolutePath)
  if (!probe) {
    console.error(`${ansi.red}Could not read video:${ansi.reset} ${absolutePath}`)
    process.exit(1)
  }
  return {
    fileNum: index + 1,
    absolutePath,
    color: getStreamColor(index),
    initialSize: fileSize(absolutePath),
    durationSeconds: probe.durationSeconds,
    hasAudio: probe.hasAudio,
    state: 'running',
    elapsedMs: 0,
    encodedSeconds: 0,
    outputSize: 0
  }
})

let footerDrawn = false

function clearFooter() {
  if (!isTTY || !footerDrawn) return
  process.stdout.write('\r\x1b[K')
  footerDrawn = false
}

function fileStatusSegment(input) {
  if (input.state === 'running') {
    const percent =
      input.durationSeconds && input.durationSeconds > 0
        ? Math.min(99, Math.floor((input.encodedSeconds / input.durationSeconds) * 100))
        : null
    const progress = percent === null ? '…' : `${percent}%`
    return {
      plain: `F${input.fileNum} ${progress}`,
      colored: `${input.color}F${input.fileNum}${ansi.reset} ${ansi.yellow}${progress}${ansi.reset}`
    }
  }
  const mark = input.state === 'pass' ? '✔' : '✘'
  const markColor = input.state === 'pass' ? ansi.green : ansi.red
  const timing = `(${formatDuration(input.elapsedMs)})`
  return {
    plain: `F${input.fileNum} ${mark} ${timing}`,
    colored: `${input.color}F${input.fileNum}${ansi.reset} ${markColor}${mark}${ansi.reset} ${ansi.dim}${timing}${ansi.reset}`
  }
}

function drawFooter() {
  if (!isTTY) return
  const budget = terminalWidth() - 1
  const elapsed = formatDuration(performance.now() - overallStartedAt)
  const segments = [
    {
      plain: `Duration: ${elapsed} | `,
      colored: `${ansi.gray}Duration:${ansi.reset} ${ansi.bold}${elapsed}${ansi.reset} ${ansi.gray}|${ansi.reset} `
    }
  ]
  inputs.forEach((input, index) => {
    if (index > 0) segments.push({ plain: ' · ', colored: `${ansi.gray} · ${ansi.reset}` })
    segments.push(fileStatusSegment(input))
  })

  let width = 0
  let line = ''
  for (const segment of segments) {
    if (width + segment.plain.length > budget) break
    width += segment.plain.length
    line += segment.colored
  }

  process.stdout.write(`\r\x1b[K${line}`)
  footerDrawn = true
}

function log(colored) {
  clearFooter()
  process.stdout.write(`${colored}\n`)
  drawFooter()
}

function logStreamLine(input, text) {
  const prefix = `[File ${input.fileNum}]`
  const body = clip(text.trimEnd(), terminalWidth() - prefix.length - 2)
  if (!body) return
  log(`${input.color}${prefix}${ansi.reset} ${ansi.dim}${body}${ansi.reset}`)
}

const encodedSecondsPattern = /time=(\d+):(\d\d):(\d\d(?:\.\d+)?)/g

function readEncodedSeconds(text) {
  let seconds = null
  for (const match of text.matchAll(encodedSecondsPattern)) {
    seconds = Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3])
  }
  return seconds
}

function buildEncodeArgs(input, outputPath, normalize) {
  const args = ['-y', '-nostdin', '-hide_banner', '-i', input.absolutePath]

  const silentAudioDuration = input.durationSeconds
  if (normalize && !input.hasAudio) {
    args.push('-f', 'lavfi')
    if (silentAudioDuration) args.push('-t', String(silentAudioDuration))
    args.push('-i', 'anullsrc=channel_layout=stereo:sample_rate=48000')
  }

  if (normalize) {
    args.push('-filter_complex', `[0:v]${NORMALIZE_FILTER}[v]`, '-map', '[v]')
    args.push('-map', input.hasAudio ? '0:a:0' : '1:a:0')
    args.push('-r', '60')
  }

  args.push('-c:v', 'libx264', '-crf', '23')

  if (normalize || input.hasAudio) {
    args.push('-c:a', 'aac', '-b:a', '128k')
  } else {
    args.push('-an')
  }

  if (normalize && !input.hasAudio && !silentAudioDuration) args.push('-shortest')

  args.push(outputPath)
  return args
}

function runEncode(input, outputPath, normalize) {
  return new Promise((resolve) => {
    const startedAt = performance.now()
    const child = spawn('ffmpeg', buildEncodeArgs(input, outputPath, normalize), {
      stdio: ['ignore', 'pipe', 'pipe']
    })

    const buffers = { stdout: '', stderr: '' }

    const consume = (streamName) => (chunk) => {
      const pending = `${buffers[streamName]}${chunk.toString('utf8')}`
      const lines = pending.split(/\r\n|\r|\n/)
      buffers[streamName] = lines.pop() ?? ''
      for (const line of lines) {
        const encodedSeconds = readEncodedSeconds(line)
        if (encodedSeconds !== null) input.encodedSeconds = encodedSeconds
        logStreamLine(input, line)
      }
      if (isTTY) drawFooter()
    }

    child.stdout.on('data', consume('stdout'))
    child.stderr.on('data', consume('stderr'))

    child.on('close', (code) => {
      for (const streamName of ['stdout', 'stderr']) {
        if (buffers[streamName].trim()) logStreamLine(input, buffers[streamName])
      }

      input.elapsedMs = performance.now() - startedAt
      input.outputSize = fileSize(outputPath)
      input.state = code === 0 && input.outputSize > 0 ? 'pass' : 'fail'

      const verdict =
        input.state === 'pass' ? `${ansi.green}pass` : `${ansi.red}fail`
      log(
        `${input.color}[File ${input.fileNum}]${ansi.reset} === ${verdict} ${ansi.dim}(${formatDuration(input.elapsedMs)})${ansi.reset} ===`
      )
      resolve(input.state === 'pass')
    })
  })
}

function runConcat(listPath, outputPath) {
  return new Promise((resolve) => {
    const child = spawn(
      'ffmpeg',
      ['-y', '-nostdin', '-hide_banner', '-f', 'concat', '-safe', '0', '-i', listPath, '-c', 'copy', outputPath],
      { stdio: ['ignore', 'ignore', 'pipe'] }
    )

    let stderr = ''
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString('utf8')
    })

    child.on('close', (code) => {
      resolve({ ok: code === 0 && fileSize(outputPath) > 0, stderr })
    })
  })
}

const tempOutputs = new Map()
const tempFileListPath = path.join(
  os.tmpdir(),
  `vcc_concat_${process.pid}_${Math.floor(Math.random() * 10000)}.txt`
)

function cleanupTempFiles() {
  for (const tempFile of [...tempOutputs.values(), tempFileListPath]) {
    try {
      fs.unlinkSync(tempFile)
    } catch {}
  }
  tempOutputs.clear()
}

function restoreTerminal() {
  if (!isTTY) return
  clearFooter()
  process.stdout.write('\x1b[?25h')
}

process.on('exit', () => {
  cleanupTempFiles()
  restoreTerminal()
})
process.on('SIGINT', () => {
  process.exit(130)
})

if (isTTY) process.stdout.write('\x1b[?25l')

const outputDir = path.dirname(files[0])
const isSingle = inputs.length === 1
const finalOutput = isSingle
  ? path.join(
      outputDir,
      `compress_${path.basename(files[0], path.extname(files[0]))}.mp4`
    )
  : path.join(outputDir, `concat_${localTimestamp()}.mp4`)

console.log(
  isSingle
    ? `${ansi.bold}Compressing single video:${ansi.reset} ${ansi.cyan}${path.basename(files[0])}${ansi.reset}`
    : `${ansi.bold}Processing ${inputs.length} files in PARALLEL:${ansi.reset}`
)

const footerTimer = isTTY ? setInterval(drawFooter, 250) : null
if (isTTY) drawFooter()

const results = await Promise.all(
  inputs.map((input) => {
    if (isSingle) return runEncode(input, finalOutput, false)
    const tempOutput = path.join(os.tmpdir(), `vcc_part_${process.pid}_${input.fileNum}.mp4`)
    tempOutputs.set(input.fileNum, tempOutput)
    return runEncode(input, tempOutput, true)
  })
)

if (footerTimer) clearInterval(footerTimer)
clearFooter()

if (!results.every(Boolean)) {
  console.error(
    `${ansi.red}One or more video segments failed to compress. Aborting merge.${ansi.reset}`
  )
  process.exit(1)
}

let concatDurationMs = 0
if (!isSingle) {
  console.log(`\n${ansi.bold}Merging temporary files into layout...${ansi.reset}`)
  const concatStartedAt = performance.now()

  fs.writeFileSync(
    tempFileListPath,
    inputs.map((input) => `file '${tempOutputs.get(input.fileNum)}'\n`).join('')
  )

  const concat = await runConcat(tempFileListPath, finalOutput)
  concatDurationMs = performance.now() - concatStartedAt

  if (!concat.ok) {
    console.error(`${ansi.red}Merge failed.${ansi.reset}`)
    console.error(concat.stderr.trimEnd())
    process.exit(1)
  }
}

const totalInitialBytes = inputs.reduce((total, input) => total + input.initialSize, 0)
const finalBytes = fileSize(finalOutput)
const totalSavedBytes = totalInitialBytes - finalBytes
const totalPercent =
  totalInitialBytes > 0 ? ((totalSavedBytes / totalInitialBytes) * 100).toFixed(1) : '0.0'

console.log(`\n${ansi.bold}${ansi.green}=== compression & merge summary ===${ansi.reset}`)
for (const input of inputs) {
  const saved = input.initialSize - input.outputSize
  const percent = input.initialSize > 0 ? ((saved / input.initialSize) * 100).toFixed(0) : '0'
  const sizeInfo = saved > 0 ? ` (${percent}% smaller)` : ''
  console.log(
    `${ansi.green}pass${ansi.reset} ${input.color}File ${input.fileNum}${ansi.reset} ${ansi.dim}(${formatDuration(input.elapsedMs)})${ansi.reset} -> ${path.basename(input.absolutePath)}${ansi.gray}${sizeInfo}${ansi.reset}`
  )
}

if (!isSingle) {
  console.log(
    `${ansi.green}pass${ansi.reset} ${ansi.purple}Concat${ansi.reset} ${ansi.dim}(${formatDuration(concatDurationMs)})${ansi.reset} -> Merging timeline chunks`
  )
}

const savingsColor = totalSavedBytes >= 0 ? ansi.green : ansi.yellow
const savingsLabel = totalSavedBytes >= 0 ? 'Saved' : 'Grew'
console.log(
  `\n${ansi.gray}Size Savings:${ansi.reset} ${ansi.bold}${formatSize(totalInitialBytes)}${ansi.reset} -> ${ansi.bold}${formatSize(finalBytes)}${ansi.reset} ${savingsColor}(${savingsLabel} ${formatSize(Math.abs(totalSavedBytes))} / ${Math.abs(Number(totalPercent))}%)${ansi.reset}`
)
console.log(
  `${ansi.gray}Total Duration:${ansi.reset} ${ansi.bold}${formatDuration(performance.now() - overallStartedAt)}${ansi.reset}`
)
console.log(
  `${ansi.green}All processes completed successfully.${ansi.reset}\nSaved to: ${ansi.bold}${finalOutput}${ansi.reset}\n`
)
