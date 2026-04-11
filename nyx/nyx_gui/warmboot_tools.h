/*
 * Copyright (c) 2018-2025 CTCaer
 *
 * This program is free software; you can redistribute it and/or modify it
 * under the terms and conditions of the GNU General Public License,
 * version 2, as published by the Free Software Foundation.
 *
 * This program is distributed in the hope it will be useful, but WITHOUT
 * ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
 * FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
 * more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#ifndef _WARMBOOT_TOOLS_H_
#define _WARMBOOT_TOOLS_H_

#include <bdk.h>

// Error codes
typedef enum {
	WB_SUCCESS                   = 0,
	WB_ERR_NULL_INFO            = 1,
	WB_ERR_ERISTA_NOT_SUPPORTED = 2,
	WB_ERR_MALLOC_PKG1         = 3,
	WB_ERR_MMC_INIT             = 4,
	WB_ERR_MMC_READ             = 5,
	WB_ERR_PKG1_ID              = 6,
	WB_ERR_DECRYPT              = 7,
	WB_ERR_PK11_MAGIC           = 8,
	WB_ERR_WB_SIZE             = 9,
	WB_ERR_MALLOC_WB            = 10,
	WB_ERR_SD_SAVE              = 11,
	WB_ERR_SC7EXIT_LOAD         = 12,
	WB_ERR_SC7EXIT_FUSES        = 13,
} wb_extract_error_t;

typedef struct {
	u8 *data;
	u32 size;
	u8 burnt_fuses;      // System's actual burnt fuse count (ODM7 only)
	u8 fuses_fw;         // Firmware's expected fuse count (derived from mkey)
	u8 firmware_mkey;    // Firmware mkey version
	bool is_mariko;
	bool success;
	const char *error_msg;
} warmboot_info_t;

// Function prototypes
bool is_mariko(void);
u8 get_burnt_fuses_wb(void);
const char *wb_error_to_string(wb_extract_error_t err);
wb_extract_error_t extract_warmboot_from_pkg1(warmboot_info_t *wb_info);
bool save_warmboot_to_sd(const warmboot_info_t *wb_info, char *path_out);
void get_warmboot_path(char *path, size_t path_size, u8 fuses_fw);

#endif
