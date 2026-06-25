// SPDX-FileCopyrightText: 2026 TechFlag
// SPDX-License-Identifier: MIT
export function startHorizontalDragScroll(event: PointerEvent) {
  if (event.button !== 0) return

  const container = event.currentTarget as HTMLElement | null
  if (!container || container.scrollWidth <= container.clientWidth) return

  const startX = event.clientX
  const startLeft = container.scrollLeft
  let didMove = false

  const onPointerMove = (moveEvent: PointerEvent) => {
    const deltaX = moveEvent.clientX - startX
    if (Math.abs(deltaX) > 2) {
      didMove = true
      container.classList.add('is-dragging')
    }
    container.scrollLeft = startLeft - deltaX
    moveEvent.preventDefault()
  }

  const stopDragging = () => {
    container.classList.remove('is-dragging')
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', stopDragging)
    window.removeEventListener('pointercancel', stopDragging)
    if (didMove) {
      window.setTimeout(() => {
        container.classList.remove('is-dragging')
      }, 0)
    }
  }

  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', stopDragging, { once: true })
  window.addEventListener('pointercancel', stopDragging, { once: true })
}
