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
        if (EventFlag(49210000)) {
            $InitializeCommonEvent(0, 90055000, 49215200, 1, 49212200, 49210201);
            $InitializeCommonEvent(0, 90055001, 49215200, 1, 49210201, 49210200);
        }
        if (EventFlag(49210001)) {
            $InitializeCommonEvent(0, 90055000, 49215200, 2, 49212200, 49210201);
            $InitializeCommonEvent(0, 90055001, 49215200, 2, 49210201, 49210200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 49210200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 49212200, 49210200);
        $InitializeCommonEvent(0, 99055400, 49212200, 49210200);
        $InitializeCommonEvent(0, 99055300, 49212200, 49210200);
        $InitializeCommonEvent(0, 99055200, 49210200, 49210800, 49210810);
    }
    $InitializeCommonEvent(0, 90065910, 49210200, 49210205, 49210800, 920100, 690047, 49215210, 49210800, 904980600, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90065911, 49210200, 49210800, 920100, 49215210, 49210800, 904980600, 0, 0, 0, 0, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 49210800, 2, 0, 0, 1050, 920100, 904980600, 49210800);
    }
    $InitializeCommonEvent(0, 90015012, 49215210, 49210200);
    $InitializeCommonEvent(1, 90015012, 0, 49210200);
    $InitializeCommonEvent(0, 90015020, 49210200, 49210800);
    $InitializeCommonEvent(0, 90015008, 49210205, 49210800, 920100, 49210800, 0, 0.6);
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 49212200, 49210800);
        $InitializeCommonEvent(0, 90015023, 49210200, 40, 0, 49215210, 49210800, 904980600, 0, 0, 0, 0);
        $InitializeCommonEvent(0, 90015030, 49210200, 49215210, 40, 920100, 0);
        $InitializeCommonEvent(0, 90015002, 0, 49210200, 49210800, 49215210, 1020, 920100, 110320, 904980600, 49210800);
        $InitializeCommonEvent(0, 90015470, 49212200, 49210200, 49210800, 49215210, 0, 0, 49215210);
        $InitializeCommonEvent(0, 90015446, 49215210, 49210200, 49210800, 49212200);
        $InitializeCommonEvent(0, 90015460, 49212200, 49210800);
        $InitializeCommonEvent(0, 90015460, 49212200, 0);
        $InitializeCommonEvent(0, 90015460, 49212200, 0);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015475, 49212200, 49210800);
        $InitializeCommonEvent(0, 90015475, 49212200, 0);
        $InitializeCommonEvent(0, 90015475, 49212200, 0);
    }
    $InitializeCommonEvent(0, 90035001, 49210800);
    if (2 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49210000, 49210300);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49210000, 49210300);
    }
    if (2 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49210000, 49210300);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49210000, 49210300);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49210000, 49210300);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49210000, 49210300);
    }
    if (3 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49210000, 49210301);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49210000, 49210301);
    }
    if (3 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49210000, 49210301);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49210000, 49210301);
    }
    if (3 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49210000, 49210301);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49210000, 49210301);
    }
});

$Event(49212800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3) {
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

$Event(49212810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5) {
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
    ForceAnimationPlayback(48600800, 20005, false, false, false);
    DisableCharacterHPBarDisplay(chrEntityId);
    EnableCharacterAI(chrEntityId);
    SetNetworkUpdateRate(48600800, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
});
