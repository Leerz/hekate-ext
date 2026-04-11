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

#include <bdk.h>

#include "gui_warmboot.h"
#include "gui.h"
#include "../warmboot_tools.h"
#include "../config.h"

extern hekate_config h_cfg;

lv_res_t create_window_warmboot_extractor(lv_obj_t *btn)
{
	lv_obj_t *win = nyx_create_standard_window("Warmboot Extractor", NULL);

	// Disable buttons
	nyx_window_toggle_buttons(win, true);

	lv_obj_t *desc = lv_cont_create(win, NULL);
	lv_obj_set_size(desc, LV_HOR_RES * 10 / 11, LV_VER_RES - (LV_DPI * 12 / 7));

	lv_obj_t *lb_desc = lv_label_create(desc, NULL);
	lv_obj_set_style(lb_desc, &monospace_text);
	lv_label_set_long_mode(lb_desc, LV_LABEL_LONG_BREAK);
	lv_label_set_recolor(lb_desc, true);
	lv_obj_set_width(lb_desc, lv_obj_get_width(desc));

	char *txt_buf = (char *)malloc(SZ_16K);

	// Check if Mariko
	bool mariko = is_mariko();

	strcpy(txt_buf, "#00DDFF Warmboot Extractor#\n\n");

	s_printf(txt_buf + strlen(txt_buf),
		"#C7EA46 System Information:#\n"
		"SoC Type: %s\n"
		"Burnt Fuses (ODM7): %d\n\n",
		mariko ? "Mariko (T210B01)" : "Erista (T210)",
		get_burnt_fuses_wb());

	if (!mariko) {
		strcat(txt_buf,
			"#FFFF00 NOTE:#\n"
			"Erista consoles do not need warmboot extraction.\n"
			"Atmosphere uses embedded warmboot for Erista.\n\n"
			"This tool is only for Mariko consoles.");
		lv_label_set_text(lb_desc, txt_buf);
		manual_system_maintenance(true);

		nyx_window_toggle_buttons(win, false);
		free(txt_buf);
		return LV_RES_OK;
	}

	// Mariko - proceed with extraction
	strcat(txt_buf, "[*] Extracting warmboot firmware from Package1...\n");
	lv_label_set_text(lb_desc, txt_buf);
	manual_system_maintenance(true);

	// Extract warmboot
	warmboot_info_t wb_info;
	wb_extract_error_t err = extract_warmboot_from_pkg1(&wb_info);

	if (err != WB_SUCCESS) {
		s_printf(txt_buf + strlen(txt_buf),
			"\n#FF8000 Extraction failed!#\n"
			"Error: %s\n",
			wb_error_to_string(err));

		if (wb_info.error_msg) {
			s_printf(txt_buf + strlen(txt_buf),
				"Details: %s\n",
				wb_info.error_msg);
		}

		lv_label_set_text(lb_desc, txt_buf);
		manual_system_maintenance(true);

		nyx_window_toggle_buttons(win, false);
		free(txt_buf);
		return LV_RES_OK;
	}

	// Success
	strcat(txt_buf, "[*] Warmboot extracted successfully!\n\n");

	s_printf(txt_buf + strlen(txt_buf),
		"#C7EA46 Warmboot Information:#\n"
		"Size: 0x%X (%d bytes)\n"
		"Firmware Expected Fuses: %d\n"
		"System Burnt Fuses: %d\n"
		"Firmware MKey: %d\n\n",
		wb_info.size, wb_info.size, wb_info.fuses_fw, wb_info.burnt_fuses, wb_info.firmware_mkey);

	strcat(txt_buf, "[*] Saving warmboot to SD card...\n");
	lv_label_set_text(lb_desc, txt_buf);
	manual_system_maintenance(true);

	// Mount SD and save
	if (!sd_mount()) {
		strcat(txt_buf, "\n#FF8000 Failed to mount SD card!#\n");
		lv_label_set_text(lb_desc, txt_buf);
		manual_system_maintenance(true);

		if (wb_info.data)
			free(wb_info.data);

		nyx_window_toggle_buttons(win, false);
		free(txt_buf);
		return LV_RES_OK;
	}

	char path[128];
	bool saved = save_warmboot_to_sd(&wb_info, path);

	sd_unmount();

	if (saved) {
		strcat(txt_buf, "[*] Warmboot saved successfully!\n\n");

		// Extract filename from path
		char *filename = strrchr(path, '/');
		if (filename)
			filename++;
		else
			filename = path;

		s_printf(txt_buf + strlen(txt_buf),
			"#96FF00 Location:# %s#\n\n"
			"This warmboot file uses firmware's expected\n"
			"fuse count (%d) for correct Atmosphere matching.",
			filename, wb_info.fuses_fw);
	} else {
		strcat(txt_buf, "\n#FF8000 Failed to save warmboot to SD!#\n");
	}

	lv_label_set_text(lb_desc, txt_buf);
	manual_system_maintenance(true);

	// Cleanup
	if (wb_info.data)
		free(wb_info.data);

	nyx_window_toggle_buttons(win, false);
	free(txt_buf);

	return LV_RES_OK;
}
