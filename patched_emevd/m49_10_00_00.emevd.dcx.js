// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    DCX_KRAK
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    if (IsMapVariation(0)) {
        if (EventFlag(49100000)) {
            $InitializeCommonEvent(0, 90055000, 49105200, 1, 49102200, 49100201);
            $InitializeCommonEvent(0, 90055001, 49105200, 1, 49100201, 49100200);
        }
        if (EventFlag(49100001)) {
            $InitializeCommonEvent(0, 90055000, 49105200, 2, 49102200, 49100201);
            $InitializeCommonEvent(0, 90055001, 49105200, 2, 49100201, 49100200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 49100200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 49102200, 49100200);
        $InitializeCommonEvent(0, 99055400, 49102200, 49100200);
        $InitializeCommonEvent(0, 99055300, 49102200, 49100200);
        $InitializeCommonEvent(0, 99055200, 49100200, 49100800, 49100810);
    }
    $InitializeCommonEvent(0, 90065910, 49100200, 49100205, 49100800, 475000, 690047, 49105210, 49100800, 904750000, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90065911, 49100200, 49100800, 475000, 49105210, 49100800, 904750000, 0, 0, 0, 0, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 49100800, 1, 0, 0, 1050, 475000, 904750000, 49100800);
    }
    $InitializeCommonEvent(0, 90015012, 49105210, 49100200);
    $InitializeCommonEvent(1, 90015012, 0, 49100200);
    $InitializeCommonEvent(0, 90015020, 49100200, 49100800);
    $InitializeCommonEvent(0, 90015008, 49100205, 49100800, 475000, 49100800, 14771, 0);
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 49102200, 49100800);
        $InitializeCommonEvent(0, 90015023, 49100200, 40, 0, 49105210, 49100800, 904750000, 0, 0, 0, 0);
        $InitializeCommonEvent(0, 90015030, 49100200, 49105210, 40, 475000, 0);
        $InitializeCommonEvent(0, 90015002, 0, 49100200, 49100800, 49105210, 1020, 475000, 110320, 904750000, 49100800);
        $InitializeCommonEvent(0, 90015470, 49102200, 49100200, 49100800, 49105210, 0, 0, 49105210);
        $InitializeCommonEvent(0, 90015446, 49105210, 49100200, 49100800, 49102200);
        $InitializeCommonEvent(0, 90015460, 49102200, 49100800);
        $InitializeCommonEvent(0, 90015460, 49102200, 0);
        $InitializeCommonEvent(0, 90015460, 49102200, 0);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015475, 49102200, 49100800);
        $InitializeCommonEvent(0, 90015475, 49102200, 0);
        $InitializeCommonEvent(0, 90015475, 49102200, 0);
    }
    $InitializeCommonEvent(0, 90035001, 49100800);
    if (1 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49100000, 49100300);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49100000, 49100300);
    }
    if (1 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49100000, 49100300);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49100000, 49100300);
    }
    if (1 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49100000, 49100300);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49100000, 49100300);
    }
    if (2 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49100000, 49100301);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49100000, 49100301);
    }
    if (2 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49100000, 49100301);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49100000, 49100301);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49100000, 49100301);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49100000, 49100301);
    }
});

$Event(491002800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3) {
    EndIf(EventFlag(eventFlagId));
    EndIf(EventFlag(eventFlagId2));
    WaitFor(HPRatio(chrEntityId) <= 0);
    WaitFixedTimeSeconds(4);
    WaitFor(CharacterDead(chrEntityId));
    DisplayBossHealthBar(Disabled, chrEntityId, 0, 0);
    if (assetEntityId != 0) {
        EnableAsset(assetEntityId);
    }
    if (chrEntityId2 != 0) {
        EnableCharacter(chrEntityId2);
    }
    if (!EventFlag(eventFlagId3)) {
        SetEventFlagID(eventFlagId, ON);
        EndEvent();
    }
    SetEventFlagID(eventFlagId2, ON);
    WaitFor(ElapsedSeconds(3));
    DisableCharacter(chrEntityId);
});

$Event(49102810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5) {
    if (EventFlag(eventFlagId4) || EventFlag(eventFlagId5)) {
        DisableCharacter(chrEntityId);
        DisableCharacterCollision(chrEntityId);
        ForceCharacterDeath(chrEntityId, false);
        EndEvent();
    }
L0:
    DisableCharacter(chrEntityId);
    DisableCharacterCollision(chrEntityId);
    DisableCharacterAI(chrEntityId);
    flag = EventFlag(7515) && (EventFlag(eventFlagId) || EventFlag(eventFlagId2));
    WaitFor((EventFlag(eventFlagId3)) || ElapsedSeconds(90));
    WaitFixedTimeSeconds(1);
    EnableCharacter(chrEntityId);
    EnableCharacterCollision(chrEntityId);
    EnableCharacterAI(chrEntityId);
    ForceAnimationPlayback(49100800, 20012, false, false, false);
    DisableCharacterHPBarDisplay(chrEntityId);
    DisableCharacterHPBarDisplay(49100801);
    EnableCharacterAI(chrEntityId);
    SetNetworkUpdateRate(49100800, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
});
