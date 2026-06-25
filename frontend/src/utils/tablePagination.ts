// SPDX-FileCopyrightText: 2026 TechFlag
// SPDX-License-Identifier: MIT
export const DEFAULT_TABLE_PAGE_SIZES = [10, 20, 50, 100]

export interface TablePaginationState {
  total: number
  current: number
  pageSize: number
}

export function buildTablePagination(state: TablePaginationState) {
  return {
    total: state.total,
    current: state.current,
    pageSize: state.pageSize,
    showTotal: true,
    showPageSize: true,
    pageSizeOptions: DEFAULT_TABLE_PAGE_SIZES,
  }
}
