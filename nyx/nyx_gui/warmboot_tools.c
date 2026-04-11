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

#include <string.h>
#include <stdlib.h>

#include <bdk.h>

#include "warmboot_tools.h"
#include "hos/pkg1.h"
#include "hos/hos.h"


// Check if this is Mariko hardware
bool is_mariko(void) {
	u32 odm4 = fuse_read_odm(4);

	// Extract hardware type from ODM4 bits
	u32 hw_type = ((odm4 >> 2) & 1) | (((odm4 >> 8) & 1) << 1) | (((odm4 >> 16) & 0xF) << 2);

	// Mariko hardware types: Iowa (0x04), Hoag (0x08), Calcio (0x02 on Mariko), Aula (0x10)
	if (hw_type == 0x04 || hw_type == 0x08 || hw_type == 0x10)
		return true;
	if (hw_type == 0x01)  // Icosa
		return false;
	// For 0x02 (Calcio/Copper), fall back to DRAM ID check
	return (fuse_read_dramid(false) >= 4);
}

// Read burnt fuse count - matches original hekate: ODM7 only
u8 get_burnt_fuses_wb(void) {
	return bit_count(fuse_read_odm(7));
}

// Generate warmboot cache path using firmware's expected fuse count
void get_warmboot_path(char *path, size_t path_size, u8 fuses_fw) {
	if (is_mariko()) {
		s_printf(path, "sd:/warmboot_mariko/wb_%02x.bin", fuses_fw);
	} else {
		s_printf(path, "sd:/warmboot_erista/wb_%02x.bin", fuses_fw);
	}
}

// Error code to string
const char *wb_error_to_string(wb_extract_error_t err) {
	switch (err) {
		case WB_SUCCESS:                  return "Success";
		case WB_ERR_NULL_INFO:           return "NULL info pointer";
		case WB_ERR_ERISTA_NOT_SUPPORTED: return "Erista not supported (uses embedded warmboot)";
		case WB_ERR_MALLOC_PKG1:         return "Failed to allocate Package1 buffer";
		case WB_ERR_MMC_INIT:            return "Failed to initialize eMMC";
		case WB_ERR_MMC_READ:            return "Failed to read Package1 from eMMC";
		case WB_ERR_PKG1_ID:             return "Unknown Package1 version";
		case WB_ERR_DECRYPT:             return "Package1 decryption failed";
		case WB_ERR_PK11_MAGIC:          return "PK11 magic not found";
		case WB_ERR_WB_SIZE:             return "Warmboot size invalid";
		case WB_ERR_MALLOC_WB:           return "Failed to allocate warmboot buffer";
		case WB_ERR_SD_SAVE:             return "Failed to save to SD card";
		case WB_ERR_SC7EXIT_LOAD:        return "Failed to load sc7exit_b01.bin";
		case WB_ERR_SC7EXIT_FUSES:       return "sc7exit_fuses too low for current burnt fuses";
		default:                          return "Unknown error";
	}
}

// Extract warmboot from Package1 - mirrors original hekate's bootloader/hos/pkg1.c flow
wb_extract_error_t extract_warmboot_from_pkg1(warmboot_info_t *wb_info) {
	if (!wb_info)
		return WB_ERR_NULL_INFO;

	memset(wb_info, 0, sizeof(warmboot_info_t));
	wb_info->is_mariko = is_mariko();

	if (!wb_info->is_mariko) {
		wb_info->error_msg = "Erista consoles use embedded warmboot from Atmosphere";
		return WB_ERR_ERISTA_NOT_SUPPORTED;
	}

	// Allocate buffer for Package1
	u8 *pkg1 = (u8 *)malloc(PKG1_BOOTLOADER_SIZE);
	if (!pkg1)
		return WB_ERR_MALLOC_PKG1;

	// Initialize eMMC
	if (!emmc_initialize(false)) {
		free(pkg1);
		return WB_ERR_MMC_INIT;
	}

	// Read Package1 from BOOT0
	emmc_set_partition(EMMC_BOOT0);
	if (!sdmmc_storage_read(&emmc_storage, PKG1_BOOTLOADER_MAIN_OFFSET,
		PKG1_BOOTLOADER_SIZE / EMMC_BLOCKSIZE, pkg1)) {
		emmc_end();
		free(pkg1);
		return WB_ERR_MMC_READ;
	}

	// Skip T210B01 OEM header (0x170 bytes)
	u32 pk1_offset = sizeof(bl_hdr_t210b01_t);

	// Identify Package1 version from timestamp
	char build_date[15];
	const pkg1_id_t *pkg1_id = pkg1_identify(pkg1 + pk1_offset, build_date);

	if (!pkg1_id) {
		emmc_end();
		free(pkg1);
		return WB_ERR_PKG1_ID;
	}

	// Generate keys (needed for Mariko BEK to decrypt pkg1)
	// For Mariko, hos_keygen derives the BEK via SE key unwrapping (no EKS needed)
	tsec_ctxt_t tsec_ctxt = {0};
	tsec_ctxt.fw = (void *)(pkg1 + pkg1_id->tsec_off);
	tsec_ctxt.pkg1 = (void *)pkg1;
	tsec_ctxt.pkg11_off = pkg1_id->pkg11_off;

	// Read EKS for the firmware version
	const u32 eks_size = sizeof(pkg1_eks_t);
	pkg1_eks_t *eks = (pkg1_eks_t *)malloc(eks_size);
	emmc_set_partition(EMMC_BOOT0);
	sdmmc_storage_read(&emmc_storage, PKG1_HOS_EKS_OFFSET + (pkg1_id->mkey * eks_size) / EMMC_BLOCKSIZE,
		eks_size / EMMC_BLOCKSIZE, eks);

	if (!hos_keygen(eks, pkg1_id->mkey, &tsec_ctxt)) {
		free(eks);
		emmc_end();
		free(pkg1);
		return WB_ERR_DECRYPT;
	}
	free(eks);

	// Decrypt Package1.1 (Stage 1: decrypts the entire pkg11 blob)
	if (!pkg1_decrypt(pkg1_id, pkg1)) {
		emmc_end();
		free(pkg1);
		return WB_ERR_DECRYPT;
	}

	// Allocate warmboot buffer
	u8 *warmboot = (u8 *)malloc(SZ_256K);
	if (!warmboot) {
		emmc_end();
		free(pkg1);
		return WB_ERR_MALLOC_WB;
	}

	// Extract warmboot from PK11 container using existing infrastructure
	pkg1_unpack(warmboot, NULL, NULL, pkg1_id, pkg1 + pk1_offset);

	// Get warmboot size from PK11 header
	pk11_hdr_t *hdr_pk11 = (pk11_hdr_t *)(pkg1 + pk1_offset + pkg1_id->pkg11_off + 0x20);
	u32 wb_size = hdr_pk11->wb_size;

	if (wb_size < 0x100 || wb_size >= SZ_256K) {
		emmc_end();
		free(pkg1);
		free(warmboot);
		return WB_ERR_WB_SIZE;
	}

	// Get fuse counts
	u8 burnt_fuses = get_burnt_fuses_wb();

	// Derive firmware's expected fuse count from mkey.
	// Map mkey to the fuses value for the LATEST firmware in each mkey generation.
	// Matches the bootloader _pkg1_ids table fuses column.
	// Mkey 0-9: unique fuses per mkey.
	// Mkey 10: fuses=14 (11.0.0+ latest), overriding the earlier 12/13 from 10.0.0-10.2.0.
	// Mkey 11: fuses=15 (12.1.0).
	// Mkey 12: fuses=16 (13.2.1, overriding fuses=15 from 13.0.0-13.2.0).
	// Mkey 13-16: one fuses per mkey (latest in range).
	// Mkey 17: shares fuses=19 with mkey 16.
	// Mkey 18-21: one fuses per mkey.
	static const u8 mkey_to_fuses[] = {
		1,  3,  4,  5,  6,  7,  8,  9, 10, 11,  // 0-9:  {1,3,4,5,6,7,8,9,10,11}
		14, 15, 16, 16, 17, 18, 19, 19, 20, 21,  // 10-19: {14,15,16,16,17,18,19,19,20,21}
		22, 23                                  // 20-21: {22,23}
	};
	u8 fuses_fw = 0;
	if (pkg1_id->mkey < sizeof(mkey_to_fuses))
		fuses_fw = mkey_to_fuses[pkg1_id->mkey];

	// Check if we need sc7exit_b01.bin fallback
	if (burnt_fuses > fuses_fw) {
		u32 sc7_size = 0;
		void *sc7_data = sd_file_read("bootloader/sys/l4t/sc7exit_b01.bin", &sc7_size);
		if (sc7_data) {
			u32 sc7_fuses_fw = *(u32 *)sc7_data;  // First 4 bytes are fuse count
			if (burnt_fuses <= sc7_fuses_fw) {
				// Use sc7exit warmboot, update fuse count
				free(warmboot);
				warmboot = (u8 *)sc7_data + sizeof(u32);  // Skip 4-byte fuse count
				wb_size = sc7_size - sizeof(u32);
				fuses_fw = sc7_fuses_fw;
			} else {
				free(sc7_data);
			}
		}
	}

	// Cleanup pkg1 buffer (keep warmboot)
	emmc_end();
	free(pkg1);

	// Populate wb_info
	wb_info->data = warmboot;
	wb_info->size = wb_size;
	wb_info->burnt_fuses = burnt_fuses;
	wb_info->fuses_fw = fuses_fw;
	wb_info->firmware_mkey = pkg1_id->mkey;
	wb_info->success = true;

	return WB_SUCCESS;
}

// Save warmboot to SD card using firmware's expected fuse count
bool save_warmboot_to_sd(const warmboot_info_t *wb_info, char *path_out) {
	if (!wb_info || !wb_info->data || !wb_info->success)
		return false;

	// Generate path using firmware's expected fuse count (fuses_fw)
	// This matches the original hekate behavior
	char path[128];
	get_warmboot_path(path, sizeof(path), wb_info->fuses_fw);

	if (path_out)
		strcpy(path_out, path);

	// Create directory
	f_mkdir("sd:/warmboot_mariko");

	FIL fp;
	UINT bytes_written;

	if (f_open(&fp, path, FA_CREATE_ALWAYS | FA_WRITE) != FR_OK)
		return false;

	bool success = (f_write(&fp, wb_info->data, wb_info->size, &bytes_written) == FR_OK);
	f_close(&fp);

	return success && (bytes_written == wb_info->size);
}
