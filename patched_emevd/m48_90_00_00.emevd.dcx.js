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
        if (EventFlag(48900000)) {
            $InitializeCommonEvent(0, 90055000, 48905200, 1, 48902200, 48900201);
            $InitializeCommonEvent(0, 90055001, 48905200, 1, 48900201, 48900200);
        }
        if (EventFlag(48900001)) {
            $InitializeCommonEvent(0, 90055000, 48905200, 2, 48902200, 48900201);
            $InitializeCommonEvent(0, 90055001, 48905200, 2, 48900201, 48900200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 48900200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 48902200, 48900200);
        $InitializeCommonEvent(0, 99055400, 48902200, 48900200);
        $InitializeCommonEvent(0, 99055300, 48902200, 48900200);
        $InitializeCommonEvent(0, 99055200, 48900200, 48900800, 48900810);
    }
    $InitializeCommonEvent(0, 90065910, 48900200, 48900205, 48900800, 921200, 690048, 48900800, 48900800, 904580600, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90065911, 48900200, 48900800, 921200, 48900800, 48900800, 904580600, 0, 0, 0, 0, 48905210);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 48900800, 1, 0, 0, 1050, 921200, 904580600, 48900800);
    }
    $InitializeCommonEvent(0, 90065100, 48900800, 48905210, 48902230, 48902231, 48902232, 48902233, 48902234, 48902235, 48900200, 48900206, 48900800);
    $InitializeCommonEvent(0, 90065101, 48900200, 48900800);
    $InitializeCommonEvent(0, 90015012, 48900800, 48900200);
    $InitializeCommonEvent(1, 90015012, 48905210, 48900200);
    $InitializeCommonEvent(0, 90015020, 48900200, 48900800);
    $InitializeCommonEvent(0, 90015008, 48900205, 48900800, 921200, 48900800, 0, 0.55);
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 48902200, 48900800);
        $InitializeCommonEvent(0, 90015023, 48900200, 40, 0, 48900800, 48900800, 904580600, 0, 0, 0, 0);
        $InitializeCommonEvent(0, 90015030, 48900200, 48900800, 40, 921200, 0);
        $InitializeCommonEvent(0, 90015002, 0, 48900200, 48900800, 48900800, 1020, 921200, 110320, 904580600, 48900800);
        $InitializeCommonEvent(0, 90015470, 48902200, 48900200, 48900800, 48900800, 48905210, 0, 0);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015446, 48900800, 48900200, 48900800, 48902200);
        $InitializeCommonEvent(0, 90015446, 48905210, 48900200, 48900800, 48902200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015460, 48902200, 48900800);
    }
    $InitializeCommonEvent(0, 90035001, 48900800);
    if (1 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 48900000, 48900300);
        $InitializeCommonEvent(0, 90015070, 1028402600, 48900000, 48900300);
    }
    if (1 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 48900000, 48900300);
        $InitializeCommonEvent(0, 90015070, 1028402601, 48900000, 48900300);
    }
    if (1 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 48900000, 48900300);
        $InitializeCommonEvent(0, 90015070, 1028402602, 48900000, 48900300);
    }
    if (2 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 48900000, 48900301);
        $InitializeCommonEvent(0, 90015070, 1028402600, 48900000, 48900301);
    }
    if (2 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 48900000, 48900301);
        $InitializeCommonEvent(0, 90015070, 1028402601, 48900000, 48900301);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 48900000, 48900301);
        $InitializeCommonEvent(0, 90015070, 1028402602, 48900000, 48900301);
    }
});

$Event(48902800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3) {
    EndIf(EventFlag(eventFlagId));
    EndIf(EventFlag(eventFlagId2));
    WaitFor(HPRatio(chrEntityId) <= 0);
    WaitFixedTimeSeconds(4);
    WaitFor(CharacterDead(chrEntityId));
    DisplayBossHealthBar(Disabled, chrEntityId, 0, 0);
    DisableGenerator(48902230);
    DisableGenerator(48902231);
    DisableGenerator(48902232);
    DisableGenerator(48902231);
    DisableGenerator(48902233);
    DisableGenerator(48902234);
    ForceCharacterDeath(48900812, false);
    ForceCharacterDeath(48900813, false);
    ForceCharacterDeath(48900814, false);
    ForceCharacterDeath(48900815, false);
    ForceCharacterDeath(48900816, false);
    ForceCharacterDeath(48900817, false);
    ForceCharacterDeath(48900818, false);
    ForceCharacterDeath(48900819, false);
    ForceCharacterDeath(48900820, false);
    ForceCharacterDeath(48900821, false);
    ForceCharacterDeath(48900822, false);
    ForceCharacterDeath(48900823, false);
    ForceCharacterDeath(48900824, false);
    ForceCharacterDeath(48900825, false);
    ForceCharacterDeath(48900826, false);
    DisableCharacter(48900812);
    DisableCharacter(48900813);
    DisableCharacter(48900814);
    DisableCharacter(48900815);
    DisableCharacter(48900816);
    DisableCharacter(48900817);
    DisableCharacter(48900818);
    DisableCharacter(48900819);
    DisableCharacter(48900820);
    DisableCharacter(48900821);
    DisableCharacter(48900822);
    DisableCharacter(48900823);
    DisableCharacter(48900824);
    DisableCharacter(48900825);
    DisableCharacter(48900826);
    DisableCharacterCollision(48900812);
    DisableCharacterCollision(48900813);
    DisableCharacterCollision(48900814);
    DisableCharacterCollision(48900815);
    DisableCharacterCollision(48900816);
    DisableCharacterCollision(48900817);
    DisableCharacterCollision(48900818);
    DisableCharacterCollision(48900819);
    DisableCharacterCollision(48900820);
    DisableCharacterCollision(48900821);
    DisableCharacterCollision(48900822);
    DisableCharacterCollision(48900823);
    DisableCharacterCollision(48900824);
    DisableCharacterCollision(48900825);
    DisableCharacterCollision(48900826);
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

$Event(48902810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5) {
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
    ForceAnimationPlayback(48900800, 20005, false, false, false);
    DisableCharacterHPBarDisplay(chrEntityId);
    DisableCharacterHPBarDisplay(48900801);
    CreateReferredDamagePair(48900801, chrEntityId);
    CreateReferredDamagePair(48900802, chrEntityId);
    EnableCharacterAI(chrEntityId);
    SetNetworkUpdateRate(48900800, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
});

$Event(48902815, Restart, function(chrEntityId) {
    DisableCharacter(48900811);
    DisableCharacterCollision(48900811);
    DisableCharacterAI(48900811);
    DisableCharacter(48900812);
    DisableCharacterCollision(48900812);
    DisableCharacterAI(48900812);
    DisableCharacter(48900817);
    DisableCharacter(48900818);
    DisableCharacter(48900819);
    DisableCharacter(48900820);
    DisableCharacterCollision(48900817);
    DisableCharacterCollision(48900818);
    DisableCharacterCollision(48900819);
    DisableCharacterCollision(48900820);
    DisableCharacterAI(48900817);
    DisableCharacterAI(48900818);
    DisableCharacterAI(48900819);
    DisableCharacterAI(48900820);
    DisableCharacter(48900815);
    DisableCharacter(48900816);
    DisableCharacterCollision(48900815);
    DisableCharacterCollision(48900816);
    DisableCharacterAI(48900815);
    DisableCharacterAI(48900816);
    WaitFor((CharacterHasSpEffect(chrEntityId, 5030)) || ElapsedSeconds(10));
    EnableCharacter(48900812);
    EnableCharacterCollision(48900812);
    EnableCharacterAI(48900812);
    EnableGenerator(48902230);
    EnableCharacter(48900817);
    EnableCharacter(48900818);
    EnableCharacter(48900819);
    EnableCharacter(48900820);
    EnableCharacterCollision(48900817);
    EnableCharacterCollision(48900818);
    EnableCharacterCollision(48900819);
    EnableCharacterCollision(48900820);
    EnableCharacterAI(48900817);
    EnableCharacterAI(48900818);
    EnableCharacterAI(48900819);
    EnableCharacterAI(48900820);
    EnableGenerator(48902232);
    EnableCharacter(48900815);
    EnableCharacter(48900816);
    EnableCharacterCollision(48900815);
    EnableCharacterCollision(48900816);
    EnableCharacterAI(48900815);
    EnableCharacterAI(48900816);
    EnableGenerator(48902235);
    EnableGenerator(48902231);
    EnableGenerator(48902233);
    EnableGenerator(48902234);
});

$Event(48902830, Restart, function(chrEntityId) {
    WaitFor((CharacterHasSpEffect(48900800, 42031)) || ElapsedSeconds(10));
    SetSpEffect(chrEntityId, 42039);
    WaitFixedTimeSeconds(1);
    SetSpEffect(chrEntityId, 5950);
    WaitFixedTimeSeconds(5);
    RestartEvent();
});

$Event(48902840, Restart, function() {
    DisableNetworkSync();
    if (IsPlayerNo(1)) {
        SetSpEffect(20000, 42180);
    }
    if (IsPlayerNo(2)) {
        SetSpEffect(20000, 42181);
    }
    if (IsPlayerNo(3)) {
        SetSpEffect(20000, 42182);
    }
});
