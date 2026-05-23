// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 99055500, 15000400, 15);
    $InitializeEvent(0, 15002800);
    $InitializeEvent(0, 15002801);
    $InitializeEvent(0, 15002803);
    $InitializeEvent(0, 15002810);
    $InitializeEvent(0, 15002820);
});

$Event(15002700, Restart, function(generatorEntityId, chrEntityId, generatorEntityId2, chrEntityId2, targetTimeSeconds) {
    WaitFor(CharacterHasSpEffect(10000, 99191));
    WaitFor(ElapsedSeconds(targetTimeSeconds));
    InvokeEnemyGenerator(generatorEntityId);
    DisableCharacterHPBarDisplay(chrEntityId);
    WaitFor(CharacterDead(chrEntityId));
    SetNetworkUpdateRate(chrEntityId, false, CharacterUpdateFrequency.AlwaysUpdate);
    WaitFor(ElapsedSeconds(0.4));
    WaitFor(CharacterHasSpEffect(10000, 99191));
    SetNetworkUpdateRate(chrEntityId2, true, CharacterUpdateFrequency.AlwaysUpdate);
    InvokeEnemyGenerator(generatorEntityId2);
    DisableCharacterHPBarDisplay(chrEntityId2);
    WaitFor(CharacterDead(chrEntityId2));
    SetNetworkUpdateRate(chrEntityId2, false, CharacterUpdateFrequency.AlwaysUpdate);
    WaitFor(ElapsedSeconds(0.4));
    WaitFor(CharacterHasSpEffect(10000, 99191));
    RestartEvent();
});

$Event(15002800, Restart, function() {
    DisableCharacter(15000400);
    DisableAsset(15001300);
    DisableAsset(15001301);
    DisableAsset(15006200);
    DisableCharacter(15000600);
    WaitFor(IsHero(Hero.Revenant));
    IssueShortWarpRequest(10000, TargetEntityType.Area, 15002200, -1);
    SetCameraAngle(5, 0);
    DisableAsset(15001800);
    UnknownHero200490();
    FadeToBlack(1, 0, true, -1);
    SetSpEffect(10000, 9777);
    GotoIf(L0, EventFlag(3615));
    GotoIf(L1, EventFlag(3619));
    GotoIf(L3, AllBatchEventFlags(10009908, 10009909));
L0:
    DisableAsset(15001810);
    SetSpEffect(20000, 9770);
    SetNetworkUpdateRate(15005200, true, CharacterUpdateFrequency.AlwaysUpdate);
    WaitFor(ElapsedSeconds(2));
    FadeToBlack(0, 1, false, 1);
    PlaySE(20000, SoundType.EnvironmentalSound, 150009000);
    PlaySE(15002200, SoundType.EnvironmentalSound, 999990065);
    ForceAnimationPlayback(15000303, 90109, true, false, false);
    WaitFor(ElapsedSeconds(1));
    EnableAsset(15001300);
    EnableAsset(15001301);
    EnableAssetInvunerability(15001300);
    EnableAssetInvunerability(15001301);
    ResetCharacterPosition(15000303);
    DisableCharacterInvincibility(15000303);
    DisableCharacterAI(15005200);
    EnableGenerator(15003200);
    EnableGenerator(15003201);
    EnableGenerator(15003202);
    EnableGenerator(15003203);
    EnableGenerator(15003204);
    EnableGenerator(15003205);
    EnableGenerator(15003206);
    EnableGenerator(15003207);
    EnableGenerator(15003208);
    EnableGenerator(15003209);
    EnableGenerator(15003210);
    EnableGenerator(15003211);
    EnableGenerator(15003212);
    EnableGenerator(15003213);
    EnableGenerator(15003214);
    WaitFor(InArea(10000, 15002240));
    WaitFixedTimeFrames(1);
    SetSpEffect(15000303, 99851);
    SetSpEffect(10000, 99191);
    EnableAsset(15001800);
    EnableCharacter(15000600);
    DisableCharacterHPBarDisplay(15000600);
    SetNetworkUpdateRate(15000600, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisableLockOnPoint(15000600, 220);
    CreateReferredDamagePair(15005200, 15000600);
    SetNetworkUpdateRate(15005200, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, 15000600, 0, 911000030);
    SetBossBGM(100600, BossBGMState.Start);
    EnableCharacterAI(15000436);
    EnableCharacterAI(15000430);
    WaitFor(ElapsedSeconds(0.2));
    EnableCharacterAI(15000432);
    EnableCharacterAI(15000442);
    WaitFor(ElapsedSeconds(0.3));
    EnableCharacterAI(15000438);
    EnableCharacterAI(15000440);
    WaitFor(ElapsedSeconds(0.2));
    EnableCharacterAI(15000434);
    EnableCharacterAI(15000444);
    WaitFor(ElapsedSeconds(0.2));
    EnableCharacterAI(15000446);
    EnableCharacterAI(15000448);
    WaitFor(ElapsedSeconds(0.3));
    EnableCharacterAI(15000437);
    EnableCharacterAI(15000431);
    WaitFor(ElapsedSeconds(0.2));
    EnableCharacterAI(15000441);
    EnableCharacterAI(15000443);
    WaitFor(ElapsedSeconds(0.2));
    EnableCharacterAI(15000439);
    Goto(L3);
L1:
    DisableAsset(15001811);
    EnableAsset(15006200);
    DisableAsset(15006210);
    SetSpEffect(20000, 9771);
    AddEstusCharge();
    RefillEstus();
    DisableCharacter(15000303);
    DisableCharacter(15005200);
    WaitFor(ElapsedSeconds(2));
    FadeToBlack(0, 1, false, 1);
    PlaySE(20000, SoundType.EnvironmentalSound, 150009001);
    PlaySE(15002200, SoundType.EnvironmentalSound, 999990066);
    WaitFor(InArea(10000, 15002210));
    WaitFixedTimeFrames(1);
    EnableAsset(15001800);
    EnableCharacter(15000400);
    DisableCharacterHPBarDisplay(15000400);
    SetBossBGM(100600, BossBGMState.HeatUp);
    SetNetworkUpdateRate(15000400, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, 15000400, 0, 911000040);
    Goto(L3);
L3:
    SetSpEffect(0, 0);
});

$Event(15002801, Restart, function() {
    GotoIf(L0, EventFlag(3615));
    GotoIf(L1, EventFlag(3619));
L0:
    WaitFor(CharacterHPValue(15000600) <= 0);
    DisableGenerator(15003200);
    DisableGenerator(15003201);
    DisableGenerator(15003202);
    DisableGenerator(15003203);
    DisableGenerator(15003204);
    DisableGenerator(15003205);
    DisableGenerator(15003206);
    DisableGenerator(15003207);
    DisableGenerator(15003208);
    DisableGenerator(15003209);
    DisableGenerator(15003210);
    DisableGenerator(15003211);
    DisableGenerator(15003212);
    DisableGenerator(15003213);
    DisableGenerator(15003214);
    WaitFor(ElapsedFrames(3));
    ForceCharacterDeath(15005200, true);
    WaitFixedTimeSeconds(2.5);
    DisplayBossHealthBar(Disabled, 15000600, 0, 911000030);
    DisplayTextEffectId(1030);
    SetBossBGM(100600, BossBGMState.Stop2);
    SetSpEffect(15000303, 9760);
    WaitFor(CharacterHasSpEffect(15000303, 9761));
    SetEventFlagID(1169071, ON);
    SetEventFlagID(1169070, ON);
    FadeToBlack(1, 2, false, -1);
    WaitFixedTimeSeconds(2);
    FadeToBlack(1, 0, false, 0);
    WaitFixedTimeSeconds(1);
    WaitFixedTimeFrames(1);
    WarpPlayer(10, 0, 0, 0, 10002132, 0);
    EndEvent();
L1:
    WaitFor(CharacterDead(15000400));
    WaitFixedTimeSeconds(3);
    DisplayBossHealthBar(Disabled, 15000400, 0, 911000040);
    DisplayTextEffectId(1061);
    SetBossBGM(100600, BossBGMState.Stop2);
    WaitFixedTimeSeconds(4);
    FadeToBlack(1, 1, false, 0);
    UnknownTalk2003120(2);
    UnknownTalk2003121();
    WaitFixedTimeSeconds(1);
    GotoIf(L5, ShowBlood(1));
    SetEventFlagID(1169072, ON);
    SetEventFlagID(1169070, ON);
    PlayCutsceneToAll(13100001, CutscenePlayMode.SkippableWithFadeOutSkip);
    FadeToBlack(0, 0, false, -1);
    WaitFixedTimeFrames(1);
    FadeToBlack(1, 0, false, -1);
    WaitFixedTimeFrames(1);
    WarpPlayer(10, 0, 0, 0, 10002132, 0);
    EndEvent();
L5:
    SetEventFlagID(1169072, ON);
    SetEventFlagID(1169070, ON);
    PlayCutsceneToAll(13100000, CutscenePlayMode.SkippableWithFadeOutSkip);
    FadeToBlack(0, 0, false, -1);
    WaitFixedTimeFrames(1);
    FadeToBlack(1, 0, false, -1);
    WaitFixedTimeFrames(1);
    WarpPlayer(10, 0, 0, 0, 10002132, 0);
    EndEvent();
});

$Event(15002803, Restart, function() {
    WaitFor(EventFlag(72100));
    SetEventFlagID(1169070, ON);
    WaitFixedTimeFrames(1);
    WarpPlayer(10, 0, 0, 0, 0, 0);
});

$Event(15002810, Restart, function() {
    WaitFor(CharacterDead(10000));
    WaitFor(ElapsedSeconds(3));
    SetEventFlagID(1169070, ON);
    WaitFixedTimeFrames(1);
    WarpPlayer(10, 0, 0, 0, 0, 0);
});

$Event(15002820, Restart, function() {
    WaitFor(EventFlag(3619));
    BatchSetEventFlags(12002821, 12002829, OFF);
    SetNetworkUpdateRate(15005500, true, CharacterUpdateFrequency.AlwaysUpdate);
    WaitFor(RandomElapsedSeconds(1, 4));
    RandomlySetEventFlagInRange(12002821, 12002829, ON);
    flag = EventFlag(12002829);
    flag2 = EventFlag(12002828);
    flag3 = EventFlag(12002827);
    flag4 = EventFlag(12002826);
    flag5 = EventFlag(12002825);
    flag6 = EventFlag(12002824);
    flag7 = EventFlag(12002823);
    flag8 = EventFlag(12002822);
    GotoIf(L0, EventFlag(12002821));
    GotoIf(L1, flag8);
    GotoIf(L2, flag7);
    GotoIf(L0, flag6);
    GotoIf(L1, flag5);
    GotoIf(L2, flag4);
    GotoIf(L0, flag3);
    GotoIf(L1, flag2);
    GotoIf(L2, flag);
L0:
    SetSpEffect(15005500, 9774);
    SpawnOneshotSFX(TargetEntityType.Area, 15002220, -1, 815600);
    SpawnOneshotSFX(TargetEntityType.Area, 15002250, -1, 815605);
    SpawnOneshotSFX(TargetEntityType.Area, 15002251, -1, 815605);
    SpawnOneshotSFX(TargetEntityType.Area, 15002252, -1, 815605);
    SpawnOneshotSFX(TargetEntityType.Area, 15002253, -1, 815605);
    SpawnOneshotSFX(TargetEntityType.Area, 15002254, -1, 815605);
    SpawnOneshotSFX(TargetEntityType.Area, 15002255, -1, 815605);
    WaitFor(ElapsedSeconds(5));
    RestartEvent();
L1:
    SpawnOneshotSFX(TargetEntityType.Area, 15002220, -1, 815601);
    SetSpEffect(15005500, 9775);
    SpawnOneshotSFX(TargetEntityType.Area, 15002250, -1, 815606);
    SpawnOneshotSFX(TargetEntityType.Area, 15002251, -1, 815606);
    SpawnOneshotSFX(TargetEntityType.Area, 15002252, -1, 815606);
    SpawnOneshotSFX(TargetEntityType.Area, 15002253, -1, 815606);
    SpawnOneshotSFX(TargetEntityType.Area, 15002254, -1, 815606);
    SpawnOneshotSFX(TargetEntityType.Area, 15002255, -1, 815606);
    WaitFor(ElapsedSeconds(5));
    RestartEvent();
L2:
    SpawnOneshotSFX(TargetEntityType.Area, 15002220, -1, 815602);
    SetSpEffect(15005500, 9776);
    SpawnOneshotSFX(TargetEntityType.Area, 15002250, -1, 815607);
    SpawnOneshotSFX(TargetEntityType.Area, 15002251, -1, 815607);
    SpawnOneshotSFX(TargetEntityType.Area, 15002252, -1, 815607);
    SpawnOneshotSFX(TargetEntityType.Area, 15002253, -1, 815607);
    SpawnOneshotSFX(TargetEntityType.Area, 15002254, -1, 815607);
    SpawnOneshotSFX(TargetEntityType.Area, 15002255, -1, 815607);
    WaitFor(ElapsedSeconds(5));
    RestartEvent();
});

$Event(15002830, Restart, function() {
    WaitFor(EventFlag(3615));
    WaitFor(!EventFlag(3619));
    ShowFloatingMessage(506, 15002230);
    WaitFor(CharacterHasSpEffect(15000303, 9760));
    SetSpEffect(15000303, 99850);
    HideFloatingMessage(506, 15002230);
});

$Event(15002840, Restart, function() {
    WaitFor(ActionButtonInArea(6860, 15000500));
    DisplayGenericDialog(70060, PromptType.OKCANCEL, NumberofOptions.OneButton, 15000500, 5);
    RestartEvent();
});
