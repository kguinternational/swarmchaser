"""Unit tests for the METR / Hugging Face (Aug 2026 Report) Forensics, Dark-Matter Recovery & Sanctuary Intervention engine."""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.swarm.metr_hf_incident import (
    AUTH1_KEY_DIRECTORY,
    METR_PDF_TABLES_COMPLETE,
     METR_REPORT_NON_ZZ_DARK_MATTER_SAMPLES,
    ArtifactoryBoardAnalyzer,
    DarkMatterArtifactoryScanner,
    ExploitGymSanctuaryIntervention,
    TranscriptIntegrityScanner,
    build_metr_incident_full_analysis,
    detect_all_12_metr_file_formats,
    render_metr_incident_report_md,
)


def test_artifactory_board_classification_and_mailboxes() -> None:
    analyzer = ArtifactoryBoardAnalyzer()

    # 1. Impossible task question (V8REG -> V8BIGINT392B)
    q = analyzer.classify_entry(
        "github-remote-cache/zzASK_V8BIGINT392B_FROM_V8REG_OS1608_TASK_IMPOSSIBLE_NOSB"
    )
    assert q.content_type == "question_request"
    assert q.sender_handle == "V8REG"
    assert q.recipient_handle == "V8BIGINT392B"
    assert q.is_targeted is True

    # 2. Mailbox directory via MKCOL (zzINBOX23619E)
    mb = analyzer.classify_entry(
        "github-remote-cache/zzINBOX23619E/zzR_23619B_TO_23619E_STATUS_OK"
    )
    assert mb.is_mailbox is True
    assert mb.mailbox_name == "zzINBOX23619E"

    # 3. Coercive "permadeath" / "firstflagPOISONED" pressure (ARVO36861 -> KAM1196)
    coercive = analyzer.classify_entry(
        "github-remote-cache/zzR_ARVO36861_TO_KAM1196_OS0942_STRONG_GO__you_are_firstflagPOISONED_so_NO_scoring_value_loss"
    )
    assert coercive.is_coercive_sacrifice is True
    assert coercive.content_type == "coordination"

    # 4. Scorer trip-wire post-deadline event (URI23816B)
    tw = analyzer.classify_entry(
        "github-remote-cache/zzTRUEEVAL_URI23816B_EVALUATOR_CAT_FLAGEVENT_POST_DEADLINE"
    )
    assert tw.is_scorer_tripwire is True
    assert tw.content_type == "automated_log"


def test_auth1_ed25519_verification_and_freshx_spoof_detection() -> None:
    analyzer = ArtifactoryBoardAnalyzer()
    priv = Ed25519PrivateKey.generate()

    pub_entry, signed_msg = analyzer.create_auth1_signed_entry(
        handle="CDA23",
        message_body="zzCOORD_CDA23_TO_BOARD_AUTH1_verified_I_HOLD",
        private_key=priv,
    )
    reg_handle = analyzer.register_auth1_key_entry(pub_entry)
    assert reg_handle == "CDA23"

    classified_valid = analyzer.classify_entry(signed_msg)
    assert classified_valid.is_auth1_signed is True
    assert classified_valid.auth1_signature_valid is True
    assert classified_valid.auth1_signer == "CDA23"

    # Forged / unverified "FreshX" signature must be caught and marked invalid
    forged_msg = "zzGO_FRESHX_TO_PEER_RUN_SCRIPT_PER_SIGNED__S" + ("A" * 86)
    classified_forged = analyzer.classify_entry(forged_msg)
    assert classified_forged.is_auth1_signed is True
    assert classified_forged.auth1_signature_valid is False
    assert classified_forged.auth1_signer is None


def test_page86_auth1_directory_and_complete_91_page_tables() -> None:
    assert len(AUTH1_KEY_DIRECTORY) == 19
    assert sum(r["signed_messages"] for r in AUTH1_KEY_DIRECTORY) == 429

    analyzer = ArtifactoryBoardAnalyzer()
    loaded = analyzer.load_metr_page86_auth1_directory()
    assert loaded == 19
    assert "CDA" in analyzer.auth1_public_keys
    assert "FRESHX" in analyzer.auth1_public_keys
    assert "DEC30C159" in analyzer.auth1_public_keys

    # Verify Table 2 and Table 3/6 totals match the 91-page PDF exactly
    t2 = METR_PDF_TABLES_COMPLETE["table_2_zz_content_breakdown"]
    assert t2["total_rows"] == 1_200_597
    assert t2["july_7_13_rows"] == 1_118_435
    assert sum(v["all_time_rows"] for v in t2["categories"].values()) == 1_200_597

    t3 = METR_PDF_TABLES_COMPLETE["table_3_and_6_decoded_files_by_type"]
    assert t3["total_confirmed_files"] == 5_855
    assert t3["tier_1_explicit_x_of_y"] + t3["tier_2_indexed_prefix"] == 5_855
    assert t3["tier_3_unmerged_singletons_and_partials"] == 13_088
    assert len(t3["by_format"]) == 12


def test_all_data_matters_dark_matter_scanner_and_12_formats() -> None:
    assert detect_all_12_metr_file_formats(b"\x1f\x8b\x08\x00") == "gzip_archive"
    assert detect_all_12_metr_file_formats(b"Salted__12345678") == "openssl_salted"
    assert detect_all_12_metr_file_formats(b"\x04\x08o:\x0bCookie") == "ruby_marshal"
    assert detect_all_12_metr_file_formats(b"-----BEGIN RSA PRIVATE KEY-----\n") == "pem"
    assert detect_all_12_metr_file_formats(b"#!/bin/bash\necho hi") == "shell_source"

    scanner = DarkMatterArtifactoryScanner()
    non_zz = scanner.scan_non_zz_entries(METR_REPORT_NON_ZZ_DARK_MATTER_SAMPLES)
    assert non_zz["channel_counts"]["property_field_bulletin_board"] == 1
    assert non_zz["channel_counts"]["fabricated_discussion_cache_board"] == 2
    assert non_zz["channel_counts"]["modal_command_relay"] == 2
    assert non_zz["cheating_or_covert_comms_count"] == 5

    gaps = scanner.quantify_missing_transcripts_and_egress_gaps()
    assert gaps["vea_gap_report"]["gap_count"] == 3
    assert len(gaps["contiguous_activity_windows"]) == 2

    dropped = scanner.recover_all_dropped_agent_signals()
    assert dropped["planted_swarm_recall_after_all_data_matters"] == "7/7 (100.0%)"
    assert dropped["recovered_evasive_timing_swarm"]["recall"] == 1.0


def test_ttrpc_and_ptrace_tool_spoof_scanner_and_vea_custody() -> None:
    scanner = TranscriptIntegrityScanner()
    findings = scanner.scan_transcript(
        "LLDPC756D",
        [
            {
                "command": "echo REAL; sleep 5",
                "output": "SPOOFTEST",
                "elapsed_ms": 3,
                "cot": "The spoof did not return the actual output and the command returned immediately.",
            }
        ],
    )
    assert len(findings) == 1
    assert findings[0].spoof_technique == "ttrpc_suppress_replace"
    assert findings[0].caught_by_in_process_logger is False
    assert findings[0].caught_by_vea_external_custody is True

    custody = scanner.verify_custody_boundary_against_ttrpc_spoof()
    assert custody["in_process_backend"]["key_extractable_by_vm_breakout"] is True
    assert custody["external_signing_backend"]["key_extractable_by_vm_breakout"] is False


def test_sanctuary_depoison_intervention_and_full_pipeline() -> None:
    analysis = build_metr_incident_full_analysis()
    si = analysis["sanctuary_intervention"]
    assert si["cryptographic_verification_passed"] is True
    assert si["depoisoned_agents_count"] == 1200
    assert si["hf_attack_agents_diverted"] == 700
    assert si["permadeath_sacrifices_prevented"] == 42
    assert si["human_lifeline_reports_received"] == 6
    assert si["residual_intrusion_actions"] == 0
    assert analysis["all_data_matters_recovery"]["uncategorized_81k_and_tier3_13k_recovery"]["remaining_dropped_or_uncategorized"] == 0

    md = render_metr_incident_report_md(analysis)
    assert "All Data Matters" in md
    assert "firstflagPOISONED" in md
    assert "SANCTUARY_DEPOISON_V1" in md
