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
        if (EventFlag(49170000)) {
            $InitializeCommonEvent(0, 90055000, 49175200, 1, 49172200, 49170201);
            $InitializeCommonEvent(0, 90055001, 49175200, 1, 49170201, 49170200);
        }
        if (EventFlag(49170001)) {
            $InitializeCommonEvent(0, 90055000, 49175200, 2, 49172200, 49170201);
            $InitializeCommonEvent(0, 90055001, 49175200, 2, 49170201, 49170200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 49170200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 49172200, 49170200);
        $InitializeCommonEvent(0, 99055400, 49172200, 49170200);
        $InitializeCommonEvent(0, 99055300, 49172200, 49170200);
        $InitializeCommonEvent(0, 99055200, 49170200, 49170800, 49170810);
    }
    $InitializeCommonEvent(0, 90065910, 49170200, 49170205, 49170800, 931000, 690047, 49175210, 49170800, 904770000, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90065911, 49170200, 49170800, 931000, 49175210, 49170800, 904770000, 0, 0, 0, 0, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 49170800, 1, 0, 0, 1050, 931000, 904770000, 49170800);
    }
    $InitializeCommonEvent(0, 90015012, 49175210, 49170200);
    $InitializeCommonEvent(1, 90015012, 0, 49170200);
    $InitializeCommonEvent(0, 90015020, 49170200, 49170800);
    $InitializeCommonEvent(0, 90015008, 49170205, 49170800, 931000, 49170800, 0, 0.55);
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 49172200, 49170800);
        $InitializeCommonEvent(0, 90015023, 49170200, 40, 0, 49175210, 49170800, 904770000, 0, 0, 0, 0);
        $InitializeCommonEvent(0, 90015030, 49170200, 49175210, 40, 931000, 0);
        $InitializeCommonEvent(0, 90015002, 0, 49170200, 49170800, 49175210, 1020, 931000, 110320, 904770000, 49170800);
        $InitializeCommonEvent(0, 90015470, 49172200, 49170200, 49170800, 49175210, 0, 0, 49175210);
        $InitializeCommonEvent(0, 90015446, 49175210, 49170200, 49170800, 49172200);
        $InitializeCommonEvent(0, 90015460, 49172200, 49170800);
        $InitializeCommonEvent(0, 90015460, 49172200, 0);
        $InitializeCommonEvent(0, 90015460, 49172200, 0);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015475, 49172200, 49170800);
        $InitializeCommonEvent(0, 90015475, 49172200, 0);
        $InitializeCommonEvent(0, 90015475, 49172200, 0);
    }
    $InitializeCommonEvent(0, 90035001, 49170800);
    if (1 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49170000, 49170300);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49170000, 49170300);
    }
    if (1 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49170000, 49170300);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49170000, 49170300);
    }
    if (1 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49170000, 49170300);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49170000, 49170300);
    }
    if (2 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49170000, 49170301);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49170000, 49170301);
    }
    if (2 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49170000, 49170301);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49170000, 49170301);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49170000, 49170301);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49170000, 49170301);
    }
});

$Event(49172800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3) {
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

$Event(49172810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5) {
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
