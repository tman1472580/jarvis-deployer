"use client"

import { useState, useCallback, useRef, useEffect } from "react"
import { HudBackground } from "@/components/jarvis/hud-background"
import { HudHeader } from "@/components/jarvis/hud-header"
import { TaskFolder } from "@/components/jarvis/task-folder"
import { PromptBar } from "@/components/jarvis/prompt-bar"

// Build version - forces browser to use fresh code
const BUILD_VERSION = "v3-2026-03-21"



interface TerminalEntry {
  type: "user" | "assistant" | "system"
  content: string
  timestamp?: string
}

interface TaskData {
  id: string
  session: number
  pane: number
  model: string
  contextUsed: number
  contextTotal: number
  turns: number
  status: "Idle" | "Waiting" | "Processing"
  activity: string
  terminalHistory?: TerminalEntry[]
}

// Sample data matching the original UI
const allTasks: TaskData[] = [
  {
    id: "task-1",
    session: 0,
    pane: 0,
    model: "Claude Sonnet",
    contextUsed: 22.4,
    contextTotal: 200.0,
    turns: 8,
    status: "Idle",
    activity: "Run curl wttr.in in your terminal for a quick forecast",
    terminalHistory: [
      { type: "system", content: "Session started - Claude Sonnet 4.6", timestamp: "14:30" },
      { type: "user", content: "Hey, can you help me check the weather?", timestamp: "14:31" },
      { type: "assistant", content: "Of course! However, I don't have direct internet access to check live weather data.", timestamp: "14:31" },
      { type: "user", content: "What's the weather like?", timestamp: "14:32" },
      { type: "assistant", content: "I can't directly check the weather, but you can run curl wttr.in in your terminal for a quick forecast. It's a neat command-line weather service!", timestamp: "14:32" },
      { type: "user", content: "Let me try that...", timestamp: "14:33" },
      { type: "system", content: "User executed: curl wttr.in", timestamp: "14:33" },
      { type: "user", content: "Thanks, that worked!", timestamp: "14:35" },
      { type: "assistant", content: "Great! The wttr.in service is really handy for quick weather checks. You can also try 'curl wttr.in/London' for specific cities.", timestamp: "14:35" },
      { type: "user", content: "Nice tip!", timestamp: "14:36" },
      { type: "assistant", content: "Let me know if you need anything else. I'm here to help!", timestamp: "14:36" }
    ]
  },
  {
    id: "task-2",
    session: 0,
    pane: 3,
    model: "Claude Opus",
    contextUsed: 25.5,
    contextTotal: 200.0,
    turns: 21,
    status: "Waiting",
    activity: "Which one do you want to work with? Or would you like me to help with something else?",
    terminalHistory: [
      { type: "system", content: "Session initialized", timestamp: "10:15" },
      { type: "user", content: "I need to refactor the authentication module in my app", timestamp: "10:16" },
      { type: "assistant", content: "I'd be happy to help with that! Let me scan your project structure first.", timestamp: "10:16" },
      { type: "system", content: "Scanning project files...", timestamp: "10:16" },
      { type: "assistant", content: "I found 3 files related to authentication:\n- auth.ts (main auth logic)\n- middleware.ts (route protection)\n- session.ts (session management)", timestamp: "10:17" },
      { type: "user", content: "What's wrong with the current implementation?", timestamp: "10:18" },
      { type: "assistant", content: "Looking at auth.ts, I see a few potential issues:\n1. Password hashing uses MD5 (insecure)\n2. No rate limiting on login attempts\n3. Session tokens don't expire\n4. Missing CSRF protection", timestamp: "10:19" },
      { type: "user", content: "That sounds serious. How do we fix it?", timestamp: "10:20" },
      { type: "assistant", content: "Let's tackle them one by one. First, we should migrate from MD5 to bcrypt for password hashing. This is the most critical security fix.", timestamp: "10:20" },
      { type: "user", content: "Okay, let's start with that", timestamp: "10:21" },
      { type: "assistant", content: "I'll need to:\n1. Install bcrypt package\n2. Update the hashPassword function\n3. Create a migration script for existing passwords\n4. Update the verifyPassword function", timestamp: "10:21" },
      { type: "system", content: "Installing bcrypt...", timestamp: "10:22" },
      { type: "system", content: "Package installed successfully", timestamp: "10:22" },
      { type: "assistant", content: "Which file do you want to work with first? Or would you like me to help with something else?", timestamp: "10:23" }
    ]
  },
  {
    id: "task-3",
    session: 0,
    pane: 5,
    model: "Gemini Pro",
    contextUsed: 23.1,
    contextTotal: 200.0,
    turns: 7,
    status: "Idle",
    activity: "Remote Claude likely refers to running Claude Code remotely via SSH",
    terminalHistory: [
      { type: "system", content: "Gemini 2.0 Pro initialized", timestamp: "11:00" },
      { type: "user", content: "What is Remote Claude?", timestamp: "11:01" },
      { type: "assistant", content: "Remote Claude likely refers to running Claude Code remotely via SSH or a similar protocol. This allows you to use Claude's capabilities on a remote server.", timestamp: "11:01" },
      { type: "user", content: "How do I set that up?", timestamp: "11:02" },
      { type: "assistant", content: "To set up Remote Claude, you'll typically need:\n1. SSH access to your remote server\n2. Claude CLI installed on the server\n3. Proper authentication configured\n4. Port forwarding if needed", timestamp: "11:02" },
      { type: "user", content: "Is it secure?", timestamp: "11:03" },
      { type: "assistant", content: "Yes, when configured properly. SSH provides encryption for the connection. Make sure to use key-based authentication rather than passwords for better security.", timestamp: "11:03" },
      { type: "user", content: "Thanks for the info", timestamp: "11:04" },
      { type: "assistant", content: "You're welcome! Let me know if you need help with the actual setup process.", timestamp: "11:04" }
    ]
  },
  {
    id: "task-4",
    session: 0,
    pane: 6,
    model: "Codex CLI",
    contextUsed: 23.0,
    contextTotal: 200.0,
    turns: 6,
    status: "Idle",
    activity: "Standing by whenever you're ready! Just let me know what you'd like to work on.",
    terminalHistory: [
      { type: "system", content: "Codex CLI ready", timestamp: "12:00" },
      { type: "user", content: "Can you help me write a Python script?", timestamp: "12:01" },
      { type: "assistant", content: "Absolutely! What kind of Python script do you need? I can help with:\n- Data processing\n- Web scraping\n- API integrations\n- Automation scripts\n- And much more!", timestamp: "12:01" },
      { type: "user", content: "I need a script to batch rename files", timestamp: "12:02" },
      { type: "assistant", content: "Great choice! Here's a simple batch rename script:\n\nimport os\nimport re\n\ndef batch_rename(directory, pattern, replacement):\n    for filename in os.listdir(directory):\n        new_name = re.sub(pattern, replacement, filename)\n        if new_name != filename:\n            os.rename(\n                os.path.join(directory, filename),\n                os.path.join(directory, new_name)\n            )\n\nWould you like me to customize this further?", timestamp: "12:03" },
      { type: "user", content: "That looks good, let me save it", timestamp: "12:04" },
      { type: "assistant", content: "Standing by whenever you're ready! Just let me know what you'd like to work on next.", timestamp: "12:04" }
    ]
  },
  {
    id: "task-5",
    session: 1,
    pane: 0,
    model: "Claude Sonnet",
    contextUsed: 140.0,
    contextTotal: 200.0,
    turns: 15,
    status: "Processing",
    activity: "Analyzing codebase structure and dependencies...",
    terminalHistory: [
      { type: "system", content: "Deep analysis mode activated", timestamp: "09:40" },
      { type: "user", content: "I need a comprehensive analysis of this codebase", timestamp: "09:41" },
      { type: "assistant", content: "Understood. I'll perform a deep dive into the codebase structure, dependencies, and potential issues.", timestamp: "09:41" },
      { type: "user", content: "Analyze the entire codebase and create a dependency graph", timestamp: "09:45" },
      { type: "assistant", content: "Starting comprehensive codebase analysis. This may take a few minutes for large codebases.", timestamp: "09:45" },
      { type: "system", content: "Phase 1: Scanning 847 files...", timestamp: "09:46" },
      { type: "system", content: "Phase 2: Parsing TypeScript/JavaScript modules...", timestamp: "09:47" },
      { type: "system", content: "Phase 3: Building AST for TypeScript modules...", timestamp: "09:48" },
      { type: "system", content: "Phase 4: Resolving import/export relationships...", timestamp: "09:49" },
      { type: "system", content: "Phase 5: Detecting circular dependencies...", timestamp: "09:50" },
      { type: "assistant", content: "Initial scan complete. Here's what I found:\n- Total files: 847\n- TypeScript: 623 files\n- JavaScript: 112 files\n- JSON configs: 45 files\n- Other: 67 files", timestamp: "09:51" },
      { type: "assistant", content: "Found 23 circular dependencies. Analyzing resolution paths...", timestamp: "09:52" },
      { type: "system", content: "Generating dependency graph visualization...", timestamp: "09:53" },
      { type: "assistant", content: "Critical finding: The circular dependencies are mainly in the /src/services directory. The most problematic cycle is:\nauth.ts -> user.ts -> permissions.ts -> auth.ts", timestamp: "09:54" },
      { type: "system", content: "Continuing deep analysis of affected modules...", timestamp: "09:55" }
    ]
  },
  {
    id: "task-6",
    session: 1,
    pane: 2,
    model: "Gemini Flash",
    contextUsed: 18.7,
    contextTotal: 200.0,
    turns: 10,
    status: "Waiting",
    activity: "Ready to help with the next step of the implementation.",
    terminalHistory: [
      { type: "system", content: "Gemini session started", timestamp: "13:00" },
      { type: "user", content: "Help me implement a React component", timestamp: "13:01" },
      { type: "assistant", content: "I'd be happy to help! What kind of component do you need?", timestamp: "13:01" },
      { type: "user", content: "A data table with sorting and filtering", timestamp: "13:02" },
      { type: "assistant", content: "Great choice! I'll create a flexible DataTable component. Do you want:\n1. Client-side sorting/filtering\n2. Server-side sorting/filtering\n3. Virtual scrolling for large datasets?", timestamp: "13:02" },
      { type: "user", content: "Client-side for now, but make it extensible", timestamp: "13:03" },
      { type: "assistant", content: "Perfect. I'll create a component with:\n- Configurable columns\n- Sort by any column\n- Filter by text search\n- Pagination\n- Extensible for future server-side support", timestamp: "13:03" },
      { type: "system", content: "Generating component code...", timestamp: "13:04" },
      { type: "assistant", content: "I've created the DataTable component. It exports:\n- DataTable (main component)\n- useTableSort (sorting hook)\n- useTableFilter (filtering hook)\n- useTablePagination (pagination hook)", timestamp: "13:05" },
      { type: "user", content: "Can you add row selection?", timestamp: "13:06" },
      { type: "assistant", content: "Of course! I'll add:\n- Single row selection\n- Multi-row selection with checkboxes\n- Select all functionality\n- onSelectionChange callback\n\nReady to help with the next step of the implementation.", timestamp: "13:07" }
    ]
  }
]

// Define folder stacks - each array is a stack, first item is front
interface FolderStack {
  id: string
  taskIds: string[]
  position: { x: number; y: number }
  size: { width: number; height: number }
  isMinimized: boolean
  savedPosition?: { x: number; y: number }
}

// Version 2: Using static unique IDs to avoid any collisions
const initialFolderStacks: FolderStack[] = [
  // Large main folder (single task)
  { id: "f-main-001", taskIds: ["task-1"], position: { x: 60, y: 120 }, size: { width: 480, height: 340 }, isMinimized: false },
  // Stack with 2 tasks
  { id: "f-stack-002", taskIds: ["task-2", "task-5"], position: { x: 620, y: 100 }, size: { width: 320, height: 240 }, isMinimized: false },
  // Stack with 2 tasks
  { id: "f-stack-003", taskIds: ["task-3", "task-4", "task-6"], position: { x: 700, y: 400 }, size: { width: 300, height: 220 }, isMinimized: false },
]

// Generate unique folder ID
const generateFolderId = () => `f-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`

// Deep clone helper to ensure no reference issues
const cloneInitialState = () => initialFolderStacks.map(stack => ({
  ...stack,
  id: stack.id,
  taskIds: [...stack.taskIds],
  position: { ...stack.position },
  size: { ...stack.size }
}))

export default function AICommandCenter() {
  const [tasks, setTasks] = useState<TaskData[]>(() => [...allTasks])
  const [folderStacks, setFolderStacks] = useState(cloneInitialState)
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [zIndices, setZIndices] = useState<number[]>([1, 2, 3])
  const [maxZ, setMaxZ] = useState(3)
  const [nextTaskId, setNextTaskId] = useState(7)
  const [dragTargetFolderId, setDragTargetFolderId] = useState<string | null>(null)
  const folderRefs = useRef<Map<string, DOMRect>>(new Map())
  const [mountKey] = useState(() => `${BUILD_VERSION}-${Date.now()}`)

  // Force clean state on every mount
  useEffect(() => {
    setFolderStacks(cloneInitialState())
    setTasks([...allTasks])
    setSelectedTaskId(null)
    setZIndices([1, 2, 3])
    setMaxZ(3)
  }, [])

  // Get all tasks as a map for quick lookup
  const tasksMap = new Map(tasks.map(t => [t.id, t]))
  
  // Get selected task
  const selectedTask = selectedTaskId ? tasksMap.get(selectedTaskId) : null

  // Count tasks by status
  const statusCounts = tasks.reduce((acc, task) => {
    acc[task.status] = (acc[task.status] || 0) + 1
    return acc
  }, {} as Record<string, number>)

  // Get minimized folders for positioning
  const minimizedFolders = folderStacks
    .map((stack, index) => ({ stack, index }))
    .filter(({ stack }) => stack.isMinimized)

  const handleSendPrompt = (message: string) => {
    console.log(`Sending to ${selectedTaskId}:`, message)
  }

  const handleAddTask = useCallback((model: string = "Claude Sonnet") => {
    const newTask: TaskData = {
      id: `task-${nextTaskId}`,
      session: Math.floor(Math.random() * 3),
      pane: nextTaskId,
      model: model,
      contextUsed: 0,
      contextTotal: 200.0,
      turns: 0,
      status: "Idle",
      activity: "New session initialized. Ready for instructions."
    }
    
    setTasks(prev => [...prev, newTask])
    
    const newPosition = {
      x: 100 + Math.random() * 300,
      y: 150 + Math.random() * 200
    }
    
    const newFolderId = generateFolderId()
    
    setFolderStacks(prev => [...prev, {
      id: newFolderId,
      taskIds: [newTask.id],
      position: newPosition,
      size: { width: 320, height: 240 },
      isMinimized: false
    }])
    
    const newZ = maxZ + 1
    setZIndices(prev => [...prev, newZ])
    setMaxZ(newZ)
    
    setSelectedTaskId(newTask.id)
    setNextTaskId(prev => prev + 1)
  }, [nextTaskId, maxZ])

  const handlePositionChange = useCallback((stackIndex: number, pos: { x: number; y: number }) => {
    setFolderStacks(prev => {
      const newStacks = [...prev]
      newStacks[stackIndex] = { ...newStacks[stackIndex], position: pos }
      return newStacks
    })
    
    // Update ref for this folder
    const folderId = folderStacks[stackIndex]?.id
    if (folderId) {
      const element = document.querySelector(`[data-folder-id="${folderId}"]`)
      if (element) {
        folderRefs.current.set(folderId, element.getBoundingClientRect())
      }
    }
  }, [folderStacks])

  const handleSizeChange = useCallback((stackIndex: number, size: { width: number; height: number }) => {
    setFolderStacks(prev => {
      const newStacks = [...prev]
      newStacks[stackIndex] = { ...newStacks[stackIndex], size }
      return newStacks
    })
  }, [])

  const bringToFront = useCallback((stackIndex: number) => {
    setMaxZ(prev => {
      const newZ = prev + 1
      setZIndices(prevIndices => {
        const newIndices = [...prevIndices]
        newIndices[stackIndex] = newZ
        return newIndices
      })
      return newZ
    })
  }, [])

  const handleStackItemClick = useCallback((stackIndex: number, taskId: string) => {
    setFolderStacks(prev => {
      const newStacks = [...prev]
      const stack = newStacks[stackIndex]
      const currentIndex = stack.taskIds.indexOf(taskId)
      if (currentIndex > 0) {
        const newTaskIds = [...stack.taskIds]
        newTaskIds.splice(currentIndex, 1)
        newTaskIds.unshift(taskId)
        newStacks[stackIndex] = { ...stack, taskIds: newTaskIds }
      }
      return newStacks
    })
    setSelectedTaskId(taskId)
    bringToFront(stackIndex)
  }, [bringToFront])

  // Handle dragging a stacked tab out to create a new folder
  const handleStackItemDragOut = useCallback((stackIndex: number, taskId: string, position: { x: number; y: number }) => {
    // Check if dropped on another folder (based on tab position)
    let targetFolderId: string | null = null
    
    // Calculate dropped tab position
    const droppedTabX = position.x
    const droppedTabY = position.y
    
    folderStacks.forEach((stack, idx) => {
      if (idx === stackIndex || stack.isMinimized) return
      
      // Check tab overlap
      const targetTabX = stack.position.x + 8
      const targetTabY = stack.position.y - 16
      const targetTabWidth = 160
      const targetTabHeight = 16
      const overlapThreshold = 40
      
      const tabsOverlap = (
        droppedTabX < targetTabX + targetTabWidth + overlapThreshold &&
        droppedTabX + 100 > targetTabX - overlapThreshold &&
        droppedTabY < targetTabY + targetTabHeight + overlapThreshold &&
        droppedTabY + 16 > targetTabY - overlapThreshold
      )
      
      if (tabsOverlap) {
        targetFolderId = stack.id
      }
    })
    
    // Generate new folder ID before state update to avoid race conditions
    const newFolderId = generateFolderId()
    
    setFolderStacks(prev => {
      const newStacks = prev.map(stack => ({ ...stack, taskIds: [...(stack.taskIds || [])] }))
      const sourceStackIdx = newStacks.findIndex(s => (s.taskIds || []).includes(taskId))
      
      if (sourceStackIdx === -1) return prev
      
      // Remove task from current stack
      newStacks[sourceStackIdx].taskIds = newStacks[sourceStackIdx].taskIds.filter(id => id !== taskId)
      
      const targetStackIdx = targetFolderId ? newStacks.findIndex(s => s.id === targetFolderId) : -1
      
      if (targetStackIdx >= 0) {
        // Add to target folder stack
        newStacks[targetStackIdx].taskIds = [taskId, ...(newStacks[targetStackIdx].taskIds || [])]
      } else {
        // Create new folder
        const newFolder: FolderStack = {
          id: newFolderId,
          taskIds: [taskId],
          position: position,
          size: { width: 320, height: 240 },
          isMinimized: false
        }
        newStacks.push(newFolder)
      }
      
      // Clean up empty stacks
      return newStacks.filter(stack => stack.taskIds.length > 0)
    })
    
    // Update z-indices
    setZIndices(prev => {
      // Get current folder count after potential changes
      const currentCount = folderStacks.length
      if (targetFolderId) {
        // Merged to existing folder, might remove one
        return prev.slice(0, currentCount)
      } else {
        // Added new folder
        return [...prev.slice(0, currentCount), maxZ + 1]
      }
    })
    
    if (!targetFolderId) {
      setMaxZ(prev => prev + 1)
    }
    
    setSelectedTaskId(taskId)
    setDragTargetFolderId(null)
  }, [folderStacks, maxZ])

  // Handle folder drag to detect tab overlap for visual feedback
  const handleFolderDrag = useCallback((stackIndex: number, currentPosition: { x: number; y: number }) => {
    const currentStack = folderStacks[stackIndex]
    if (!currentStack || currentStack.isMinimized || !currentStack.taskIds) return
    
    // Calculate dragging folder's tab position
    const draggingTabX = currentPosition.x + 8
    const draggingTabY = currentPosition.y - 16
    const draggingTabWidth = 160
    const draggingTabHeight = 16
    
    let targetId: string | null = null
    
    folderStacks.forEach((stack, idx) => {
      if (idx === stackIndex || stack.isMinimized || !stack.taskIds) return
      
      const targetTabX = stack.position.x + 8
      const targetTabY = stack.position.y - 16
      const targetTabWidth = 160
      const targetTabHeight = 16
      const overlapThreshold = 30
      const tabsOverlap = (
        draggingTabX < targetTabX + targetTabWidth + overlapThreshold &&
        draggingTabX + draggingTabWidth > targetTabX - overlapThreshold &&
        draggingTabY < targetTabY + targetTabHeight + overlapThreshold &&
        draggingTabY + draggingTabHeight > targetTabY - overlapThreshold
      )
      
      if (tabsOverlap) {
        targetId = stack.id
      }
    })
    
    setDragTargetFolderId(targetId)
  }, [folderStacks])

  // Handle folder drag end to check for merge
  const handleFolderDragEnd = useCallback((stackIndex: number, finalPosition: { x: number; y: number }) => {
    const currentStack = folderStacks[stackIndex]
    if (!currentStack || currentStack.isMinimized || !currentStack.taskIds) return
    
    // Check if tabs overlap - tabs are at -top-4 (16px above folder), left-0 + ml-2 (8px)
    // Tab dimensions are roughly 160px wide x 16px tall
    let targetFolderIndex = -1
    
    // Calculate dragging folder's tab position
    const draggingTabX = finalPosition.x + 8 // ml-2 = 8px
    const draggingTabY = finalPosition.y - 16 // -top-4 = 16px above
    const draggingTabWidth = 160
    const draggingTabHeight = 16
    
    folderStacks.forEach((stack, idx) => {
      if (idx === stackIndex || stack.isMinimized || !stack.taskIds) return
      
      // Calculate target folder's tab position
      const targetTabX = stack.position.x + 8
      const targetTabY = stack.position.y - 16
      const targetTabWidth = 160
      const targetTabHeight = 16
      
      // Check if tabs overlap or are very close (within 30px)
      const overlapThreshold = 30
      const tabsOverlap = (
        draggingTabX < targetTabX + targetTabWidth + overlapThreshold &&
        draggingTabX + draggingTabWidth > targetTabX - overlapThreshold &&
        draggingTabY < targetTabY + targetTabHeight + overlapThreshold &&
        draggingTabY + draggingTabHeight > targetTabY - overlapThreshold
      )
      
      if (tabsOverlap) {
        targetFolderIndex = idx
      }
    })
    
    if (targetFolderIndex >= 0) {
      const sourceId = currentStack.id
      const targetId = folderStacks[targetFolderIndex]?.id
      
      if (!targetId) return
      
      // Merge stacks using IDs to avoid index issues
      setFolderStacks(prev => {
        const sourceIdx = prev.findIndex(s => s.id === sourceId)
        const targetIdx = prev.findIndex(s => s.id === targetId)
        
        if (sourceIdx === -1 || targetIdx === -1) return prev
        
        const sourceStack = prev[sourceIdx]
        const targetStack = prev[targetIdx]
        
        // Validate both stacks exist and have taskIds
        if (!sourceStack?.taskIds || !targetStack?.taskIds) {
          return prev
        }
        
        const newStacks = prev.map(stack => ({ ...stack, taskIds: [...(stack.taskIds || [])] }))
        
        // Add all tasks from source to front of target
        newStacks[targetIdx].taskIds = [...(sourceStack.taskIds || []), ...(targetStack.taskIds || [])]
        
        // Remove source stack
        return newStacks.filter(s => s.id !== sourceId)
      })
      
      // Update z-indices
      setZIndices(prev => prev.slice(0, -1))
    }
    
    setDragTargetFolderId(null)
  }, [folderStacks, bringToFront])

  const handleMinimize = useCallback((stackIndex: number) => {
    setFolderStacks(prev => {
      const newStacks = [...prev]
      const stack = newStacks[stackIndex]
      newStacks[stackIndex] = { 
        ...stack, 
        isMinimized: true,
        savedPosition: stack.position 
      }
      return newStacks
    })
    const stack = folderStacks[stackIndex]
    if (selectedTaskId && stack.taskIds.includes(selectedTaskId)) {
      setSelectedTaskId(null)
    }
  }, [folderStacks, selectedTaskId])

  const handleExpand = useCallback((stackIndex: number) => {
    setFolderStacks(prev => {
      const newStacks = [...prev]
      const stack = newStacks[stackIndex]
      newStacks[stackIndex] = { 
        ...stack, 
        isMinimized: false,
        position: stack.savedPosition || stack.position
      }
      return newStacks
    })
    bringToFront(stackIndex)
  }, [bringToFront])

  const handleClose = useCallback((stackIndex: number) => {
    const stack = folderStacks[stackIndex]
    
    setFolderStacks(prev => {
      const newStacks = [...prev]
      newStacks.splice(stackIndex, 1)
      return newStacks
    })
    
    setTasks(prevTasks => prevTasks.filter(t => !stack.taskIds.includes(t.id)))
    
    setZIndices(prev => {
      const newIndices = [...prev]
      newIndices.splice(stackIndex, 1)
      return newIndices
    })
    
    if (selectedTaskId && stack.taskIds.includes(selectedTaskId)) {
      setSelectedTaskId(null)
    }
  }, [folderStacks, selectedTaskId])

  const handleBackgroundClick = () => {
    setSelectedTaskId(null)
  }

  return (
    <div key={mountKey} className="relative min-h-screen overflow-hidden" onClick={handleBackgroundClick}>
      <HudBackground />
      
      <div className="relative z-10 flex flex-col min-h-screen">
        {/* Header */}
        <HudHeader onAddTask={handleAddTask} />

        {/* Stats bar */}
        <div className="mx-6 mt-2 flex items-center justify-between px-4 py-3 bg-slate-900/50 border border-cyan-800/30 rounded-sm">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">Active Sessions</span>
              <span className="text-lg font-mono text-cyan-300 tabular-nums">{tasks.length}</span>
            </div>
            <div className="w-px h-6 bg-cyan-700/30" />
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">Idle</span>
              <span className="text-lg font-mono text-emerald-400 tabular-nums">
                {statusCounts["Idle"] || 0}
              </span>
            </div>
            <div className="w-px h-6 bg-cyan-700/30" />
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">Waiting</span>
              <span className="text-lg font-mono text-amber-400 tabular-nums">
                {statusCounts["Waiting"] || 0}
              </span>
            </div>
            <div className="w-px h-6 bg-cyan-700/30" />
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">Processing</span>
              <span className="text-lg font-mono text-cyan-400 tabular-nums">
                {statusCounts["Processing"] || 0}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-[10px] font-mono text-cyan-600/40 tracking-wider">
              DRAG FOLDERS TO STACK {"•"} DRAG TABS TO SEPARATE
            </span>
            <div className="flex gap-1">
              {Array.from({ length: 8 }).map((_, i) => (
                <div 
                  key={i} 
                  className={`w-1.5 h-3 ${i < 6 ? "bg-cyan-500/60" : "bg-cyan-800/40"}`}
                />
              ))}
            </div>
          </div>
        </div>

        {/* Main content area */}
        <main className="flex-1 relative" style={{ minHeight: "calc(100vh - 200px)" }}>
          {folderStacks.map((stack, stackIndex) => {
            const frontTask = tasksMap.get(stack.taskIds[0])
            if (!frontTask) return null
            
            const stackedTasks = stack.taskIds.slice(1)
              .map(id => tasksMap.get(id))
              .filter((t): t is TaskData => t !== undefined)

            const minimizedIndex = stack.isMinimized 
              ? minimizedFolders.findIndex(f => f.index === stackIndex)
              : 0

            return (
              <TaskFolder
                key={`${mountKey}-${stack.id}`}
                folderId={stack.id}
                task={frontTask}
                stackedTasks={stackedTasks}
                isSelected={selectedTaskId === frontTask.id}
                isMinimized={stack.isMinimized}
                onClick={() => setSelectedTaskId(
                  selectedTaskId === frontTask.id ? null : frontTask.id
                )}
                onStackItemClick={(taskId) => handleStackItemClick(stackIndex, taskId)}
                onStackItemDragOut={(taskId, pos) => handleStackItemDragOut(stackIndex, taskId, pos)}
                initialPosition={stack.position}
                initialSize={stack.size}
                onPositionChange={(pos) => handlePositionChange(stackIndex, pos)}
                onSizeChange={(size) => handleSizeChange(stackIndex, size)}
                onDrag={(pos) => handleFolderDrag(stackIndex, pos)}
                onDragEnd={(pos) => handleFolderDragEnd(stackIndex, pos)}
                zIndex={zIndices[stackIndex] || 1}
                onBringToFront={() => bringToFront(stackIndex)}
                onClose={() => handleClose(stackIndex)}
                onMinimize={() => handleMinimize(stackIndex)}
                onExpand={() => handleExpand(stackIndex)}
                minimizedIndex={minimizedIndex}
                isDragTarget={dragTargetFolderId === stack.id}
              />
            )
          })}
        </main>

        {/* Bottom prompt bar */}
        <footer className="sticky bottom-0 z-50 p-6 pt-0 bg-gradient-to-t from-slate-950 via-slate-950/95 to-transparent">
          <PromptBar 
            selectedTask={selectedTask ? `SESSION_${selectedTask.session}:${selectedTask.pane}` : null}
            onSend={handleSendPrompt}
          />
        </footer>
      </div>

      {/* Side decorations */}
      <div className="fixed top-1/2 left-4 -translate-y-1/2 flex flex-col gap-2 opacity-40 z-0">
        {Array.from({ length: 8 }).map((_, i) => (
          <div 
            key={i}
            className="w-1 bg-cyan-500/60"
            style={{ height: `${12 + Math.sin(i * 0.8) * 8}px` }}
          />
        ))}
      </div>
      <div className="fixed top-1/2 right-4 -translate-y-1/2 flex flex-col gap-2 opacity-40 z-0">
        {Array.from({ length: 8 }).map((_, i) => (
          <div 
            key={i}
            className="w-1 bg-cyan-500/60"
            style={{ height: `${12 + Math.cos(i * 0.8) * 8}px` }}
          />
        ))}
      </div>
    </div>
  )
}
